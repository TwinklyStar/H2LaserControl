"""List serial ports with USB identifiers (used to map devices to ports)."""

from serial.tools import list_ports


def main() -> None:
    for p in sorted(list_ports.comports(), key=lambda p: p.device):
        vid = f"{p.vid:04X}" if p.vid is not None else "----"
        pid = f"{p.pid:04X}" if p.pid is not None else "----"
        print(f"{p.device:6}  VID:PID={vid}:{pid}  serial={p.serial_number or '-':12}  {p.description}")


if __name__ == "__main__":
    main()
