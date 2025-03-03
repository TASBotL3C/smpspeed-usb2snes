#!/usr/bin/env python3

# SPDX-FileCopyrightText: © 2025 Marcus Rowe <undisbeliever@gmail.com>
# SPDX-License-Identifier: MIT

# Distributed under the MIT License (MIT)
#
# Copyright (c) 2025, Marcus Rowe <undisbeliever@gmail.com>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


import argparse
import contextlib
import datetime
import json
import time
import sched
import posixpath

from typing import Optional, Final, TextIO

import websocket  # type: ignore[import]


# SPDX-SnippetBegin
# SDPX—SnippetName: resources-over-usb2snes Usb2Snes class
# SPDX-SnippetCopyrightText: Copyright (c) 2020 - 2022, Marcus Rowe <undisbeliever@gmail.com>
# SPDX-License-Identifier: MIT


# `Usb2Snes` class from unnamed-snes-game Resources over usb2snes by undisbeliever
class Usb2Snes:
    BLOCK_SIZE: Final[int] = 1024

    USB2SNES_SRAM_OFFSET: Final[int] = 0xE00000
    USB2SNES_WRAM_OFFSET: Final[int] = 0xF50000
    USB2SNES_VRAM_OFFSET: Final[int] = 0xF70000

    def __init__(self, socket: websocket.WebSocket) -> None:
        self._socket: Final = socket
        self._device: Optional[str] = None

    def device_name(self) -> Optional[str]:
        return self._device

    def _assert_attached(self) -> None:
        if self._socket is None or self._socket.status is None:
            raise RuntimeError("Socket is closed")

        if self._device is None:
            raise RuntimeError("Not attached to device")

    def _request(self, opcode: str, *operands: str) -> None:
        self._assert_attached()
        self._socket.send(
            json.dumps(
                {
                    "Opcode": opcode,
                    "Space": "SNES",
                    "Flags": None,
                    "Operands": operands,
                }
            )
        )

    def _request_not_attached(self, opcode: str, *operands: str) -> None:
        if self._socket is None or self._socket.status is None:
            raise RuntimeError("Socket is closed")

        self._socket.send(
            json.dumps(
                {
                    "Opcode": opcode,
                    "Space": "SNES",
                    "Flags": None,
                    "Operands": operands,
                }
            )
        )

    def _response(self) -> list[str]:
        r = json.loads(self._socket.recv())
        r = r["Results"]

        if not isinstance(r, list):
            raise TypeError("Invalid response type, expected a list of strings.")

        if not all(isinstance(i, str) for i in r):
            raise TypeError("Invalid response type, expected a list of strings.")

        return r

    def _request_response(self, opcode: str, *operands: str) -> list[str]:
        self._request(opcode, *operands)
        return self._response()

    def find_and_attach_device(self) -> bool:
        """
        Look through the DeviceList and connect to the first SD2SNES reported.
        """

        self._request_not_attached("DeviceList")
        device_list = self._response()

        device = None
        for d in device_list:
            if "SD2SNES" in d.upper():
                device = d
                break

        if device is None:
            return False

        self._request_not_attached("Attach", device)

        self._device = device

        return True

    def get_playing_filename(self) -> str:
        r = self._request_response("Info")
        return r[2]

    def get_playing_basename(self) -> str:
        return posixpath.basename(self.get_playing_filename())

    def send_reset_command(self) -> None:
        # Reset command does not return a response
        self._request("Reset")

    def read_offset(self, offset: int, size: int) -> bytes:
        if size < 0:
            raise ValueError("Invalid size")

        self._request("GetAddress", hex(offset), hex(size))

        out = bytes()

        # This loop is required.
        # On my system, Work-RAM addresses are sent in 128 byte blocks.
        while len(out) < size:
            o = self._socket.recv()
            if not isinstance(o, bytes):
                raise RuntimeError(
                    f"Unknown response from QUsb2Snes, expected bytes got { type(out) }"
                )
            out += o

        if len(out) != size:
            raise RuntimeError(f"Size mismatch: got { len(out) } bytes, expected { size }")

        return out

    def write_to_offset(self, offset: int, data: bytes) -> None:
        if not isinstance(data, bytes) and not isinstance(data, bytearray):
            raise ValueError(f"Expected bytes data, got { type(data) }")

        if offset >= self.USB2SNES_WRAM_OFFSET and offset < self.USB2SNES_SRAM_OFFSET:
            raise ValueError("Cannot write to Work-RAM")

        size: Final[int] = len(data)

        if size == 0:
            return

        self._request("PutAddress", hex(offset), hex(size))

        for chunk_start in range(0, size, self.BLOCK_SIZE):
            chunk_end = min(chunk_start + self.BLOCK_SIZE, size)

            self._socket.send_binary(data[chunk_start:chunk_end])

    def read_wram_addr(self, addr: int, size: int) -> bytes:
        wram_bank = addr >> 16

        if wram_bank == 0x7E or wram_bank == 0x7F:
            return self.read_offset((addr & 0x01FFFF) | self.USB2SNES_WRAM_OFFSET, size)
        elif wram_bank & 0x7F < 0x40:
            if addr & 0xFFFF >= 0x2000:
                return self.read_offset((addr & 0x1FFF) | self.USB2SNES_WRAM_OFFSET, size)

        raise ValueError("addr is not a Work-RAM address")


# SPDX-SnippetEnd


class Logger:
    def __init__(self, file: TextIO):
        self.__file: Final = file

    def _print(self, s: str) -> None:
        print(s)
        self.__file.write(s + "\n")

    def log_string(self, message: str) -> None:
        time = datetime.datetime.now().isoformat()
        self._print(f'{ time }, "{ message }"')

    def log_data(self, data: list[str]) -> None:
        time = datetime.datetime.now().isoformat()
        self._print(f"{ time }, " + ", ".join(data))


def read_until_three_duplicates(usb2snes: Usb2Snes, offset, size) -> bytes:
    data1 = None
    data2 = None
    data3 = usb2snes.read_offset(offset, size)

    while data1 != data2 or data1 != data3:
        data1 = data2
        data2 = data3
        data3 = usb2snes.read_offset(offset, size)

    assert data1 == data2 and data1 == data3, "Bad read"

    return data3


SMPSPEED_VRAM_OFFSET: Final = 0xF50260
SMPSPEED_VRAM_SIZE: Final = 15 * 32

TILEMAP_ROWS: Final = (
    (0, b"SNES PPU:"),
    (5, b"Meaning:"),
    (6, b"Slowest:"),
    (7, b"Fastest:"),
    (9, b"S-SMP clock:"),
    (10, b"relative:"),
    (11, b"Slowest:"),
    (12, b"Fastest:"),
    (14, b"DSP sample rate:"),
)


def csv_headers(logger: Logger) -> None:
    headers = ['"' + h.decode("ASCII").replace(":", "") + '"' for r, h in TILEMAP_ROWS]
    logger._print('"Time",' + ", ".join(headers))


class TilemapReadError(Exception):
    pass


def read_tilemap_line(tilemap: bytes, row: int, header: bytes) -> str:
    h_start = row * 32 + 1
    h_end = h_start + len(header)
    row_end = (row + 1) * 32

    if tilemap[h_start:h_end] != header:
        raise TilemapReadError()

    data = tilemap[h_end:row_end].strip(b"\x00 ").split(b"\x00", 1)[0]

    return data.decode("ASCII")


def read_smpspeed(usb2snes: Usb2Snes) -> Optional[list[str]]:
    tilemap = read_until_three_duplicates(usb2snes, SMPSPEED_VRAM_OFFSET, SMPSPEED_VRAM_SIZE)

    try:
        out = [read_tilemap_line(tilemap, row, name) for row, name in TILEMAP_ROWS]
        # Fixes "60, ------, ------, ------, -------, ------, -------, -------, -----" line if read during setup
        if "---" in out[1]:
            return None
        return out
    except TilemapReadError as e:
        return None


def read_usb2snes(usb2snes: Usb2Snes, logger: Logger, interval: int) -> None:
    csv_headers(logger)
    logger.log_string(f"Connected to { usb2snes.device_name() }")

    while True:
        start_time = time.monotonic()

        data = read_smpspeed(usb2snes)
        if data is None:
            logger.log_string("Cannot read data: tilemap does not match smpspeed")

            while data is None:
                if time.monotonic() - start_time > 60:
                    raise RuntimeError("Timeout")
                time.sleep(0.25)
                data = read_smpspeed(usb2snes)
            # reset timer
            start_time = time.monotonic()

        logger.log_data(data)
        time.sleep(max(start_time - time.monotonic() + interval, 0.5))


def smpspeed_usb2snes(ws_address: str, output_filename: str, interval: int) -> None:
    with contextlib.closing(websocket.WebSocket()) as ws:
        ws.connect(ws_address, origin="http://localhost")  # type: ignore

        usb2snes = Usb2Snes(ws)

        if not usb2snes.find_and_attach_device():
            raise RuntimeError("Cannot connect to usb2snes")

        with open(output_filename, "x") as fp:
            logger = Logger(fp)

            try:
                read_usb2snes(usb2snes, logger, interval)
            except Exception as e:
                logger.log_string(f"EXCEPTION: { e }")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-a",
        "--address",
        required=False,
        default="ws://localhost:8080",
        help="Websocket address",
    )
    parser.add_argument(
        "-i",
        "--interval",
        required=False,
        type=int,
        default=5,
        help="interval between reads (seconds)",
    )
    parser.add_argument(
        "-o",
        "--csv-output",
        required=True,
        type=str,
        help="csv output file",
    )

    args = parser.parse_args()

    smpspeed_usb2snes(args.address, args.csv_output, args.interval)


if __name__ == "__main__":
    main()
