"""Minimaler DNS-Server für den Integrationstest ("Resolver des Internetproviders").

Beantwortet jede A-Anfrage mit 203.0.113.10 und protokolliert die QUELL-IP jeder
Anfrage. Damit lässt sich prüfen, ob DNS-Anfragen eines Clients am VPN vorbei
gehen (Leck) oder vom VPN-Server stammen (kein Leck).
"""

import socket
import struct
import sys

listen, logfile = sys.argv[1], sys.argv[2]
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((listen, 53))
while True:
    data, addr = sock.recvfrom(4096)
    try:
        tid, flags, qd = struct.unpack("!HHH", data[:6])
        i, labels = 12, []
        while data[i]:
            labels.append(data[i + 1 : i + 1 + data[i]].decode())
            i += data[i] + 1
        qtype, _qclass = struct.unpack("!HH", data[i + 1 : i + 5])
        question = data[12 : i + 5]
        name = ".".join(labels).lower()
    except Exception:  # noqa: BLE001
        continue
    with open(logfile, "a") as f:
        f.write(f"{addr[0]} {name} {qtype}\n")
    answers = b""
    an = 0
    if qtype == 1:
        answers = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 60, 4) + socket.inet_aton("203.0.113.10")
        an = 1
    header = struct.pack("!HHHHHH", tid, 0x8180, 1, an, 0, 0)
    sock.sendto(header + question + answers, addr)
