import socket
import threading
import json
import sys
import os

GRID_SIZE = 10
SHIPS = [
    ("Träger",      5),
    ("Schlachtsch.", 4),
    ("Kreuzer",     3),
    ("U-Boot",      3),
    ("Zerstörer",   2),
]


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def print_boards(my_board, enemy_board, my_ships, enemy_hits):
    header = f"  {'MEIN FELD':^21}     {'GEGNER':^21}"
    print(header)
    col_nums = "  " + " ".join(str(i) for i in range(GRID_SIZE))
    print(f"  {col_nums}      {col_nums}")
    for r in range(GRID_SIZE):
        my_row = ""
        en_row = ""
        for c in range(GRID_SIZE):
            cell = my_board[r][c]
            my_row += cell + " "
            en_row += enemy_board[r][c] + " "
        print(f"{r} [{my_row.rstrip()}]   {r} [{en_row.rstrip()}]")


class GameClient:
    def __init__(self):
        self.conn = None
        self.buffer = ""
        self.my_board = [["~"] * GRID_SIZE for _ in range(GRID_SIZE)]
        self.enemy_board = [["~"] * GRID_SIZE for _ in range(GRID_SIZE)]
        self.my_ships = []
        self.my_hits_recv = []
        self.my_turn = False
        self.name = ""
        self.opponent_name = ""
        self.running = True
        self.recv_lock = threading.Lock()
        self.message_queue = []
        self.queue_event = threading.Event()

    def connect(self, host, port):
        self.conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.conn.connect((host, port))

    def send(self, data):
        msg = json.dumps(data) + "\n"
        self.conn.sendall(msg.encode())

    def recv_line(self):
        while True:
            if "\n" in self.buffer:
                line, self.buffer = self.buffer.split("\n", 1)
                return json.loads(line)
            data = self.conn.recv(4096).decode()
            if not data:
                raise ConnectionError("Server getrennt")
            self.buffer += data

    def recv_thread(self):
        while self.running:
            try:
                msg = self.recv_line()
                self.message_queue.append(msg)
                self.queue_event.set()
            except Exception:
                self.running = False
                self.queue_event.set()
                break

    def wait_msg(self, expected_types=None):
        while True:
            self.queue_event.wait()
            self.queue_event.clear()
            while self.message_queue:
                msg = self.message_queue.pop(0)
                if expected_types is None or msg["type"] in expected_types:
                    return msg
                else:
                    self.handle_async(msg)

    def handle_async(self, msg):
        t = msg.get("type")
        if t == "chat":
            print(f"\n[Chat] {msg['from']}: {msg['msg']}")
        elif t == "opponent_left":
            print("\n[!] Gegner hat das Spiel verlassen.")
            self.running = False

    def place_ships(self):
        clear()
        print("=" * 50)
        print("   SCHIFFE PLATZIEREN")
        print("=" * 50)
        print("Format: Zeile Spalte Richtung (h=horizontal, v=vertikal)")
        print("Beispiel: 2 3 h  →  Schiff beginnt bei (2,3) horizontal\n")

        board = [["~"] * GRID_SIZE for _ in range(GRID_SIZE)]
        placed_ships = []

        for ship_name, length in SHIPS:
            while True:
                self.print_board_simple(board)
                print(f"\nPlatziere: {ship_name} (Länge {length})")
                try:
                    inp = input("Eingabe: ").strip().split()
                    if len(inp) != 3:
                        print("Bitte genau 3 Werte eingeben.")
                        continue
                    row, col, direction = int(inp[0]), int(inp[1]), inp[2].lower()
                    if direction not in ("h", "v"):
                        print("Richtung muss 'h' oder 'v' sein.")
                        continue
                    coords = []
                    for i in range(length):
                        r = row + (i if direction == "v" else 0)
                        c = col + (i if direction == "h" else 0)
                        coords.append([r, c])
                    # Validate
                    valid = True
                    for r, c in coords:
                        if not (0 <= r < GRID_SIZE and 0 <= c < GRID_SIZE):
                            print("Schiff liegt außerhalb des Feldes!")
                            valid = False
                            break
                        if board[r][c] != "~":
                            print("Position bereits belegt!")
                            valid = False
                            break
                    # Check adjacency
                    if valid:
                        for r, c in coords:
                            for dr in [-1, 0, 1]:
                                for dc in [-1, 0, 1]:
                                    nr, nc = r + dr, c + dc
                                    if 0 <= nr < GRID_SIZE and 0 <= nc < GRID_SIZE:
                                        if board[nr][nc] == "S" and [nr, nc] not in coords:
                                            print("Schiffe dürfen nicht aneinander grenzen!")
                                            valid = False
                    if valid:
                        for r, c in coords:
                            board[r][c] = "S"
                        placed_ships.append({"name": ship_name, "coords": coords})
                        self.my_ships.append(coords)
                        break
                except (ValueError, IndexError):
                    print("Ungültige Eingabe.")

        self.my_board = board
        return placed_ships

    def print_board_simple(self, board):
        print("  " + " ".join(str(i) for i in range(GRID_SIZE)))
        for r in range(GRID_SIZE):
            row_str = " ".join(board[r][c] for c in range(GRID_SIZE))
            print(f"{r} {row_str}")

    def game_loop(self):
        threading.Thread(target=self.recv_thread, daemon=True).start()

        while self.running:
            clear()
            print(f"=== Schiffeversenken | Du: {self.name} | Gegner: {self.opponent_name} ===")
            if self.my_turn:
                print("[>> DEIN ZUG <<]")
            else:
                print("[Warte auf Gegner...]")
            print()
            print_boards(self.my_board, self.enemy_board, self.my_ships, self.my_hits_recv)
            print()

            if self.my_turn:
                print("Schuss: Zeile Spalte  |  'c <text>' für Chat  |  'q' beenden")
                inp = input("> ").strip()

                if inp.lower() == "q":
                    break
                elif inp.lower().startswith("c "):
                    self.send({"type": "chat", "msg": inp[2:]})
                    continue
                else:
                    try:
                        parts = inp.split()
                        row, col = int(parts[0]), int(parts[1])
                        if not (0 <= row < GRID_SIZE and 0 <= col < GRID_SIZE):
                            print("Ungültige Koordinaten.")
                            input("Enter drücken...")
                            continue
                        if self.enemy_board[row][col] != "~":
                            print("Bereits geschossen!")
                            input("Enter drücken...")
                            continue
                        self.send({"type": "shoot", "row": row, "col": col})
                        self.my_turn = False
                        # Warte auf Ergebnis
                        msg = self.wait_msg(["shot_result", "opponent_left"])
                        self.process_shot_result(msg)
                    except (ValueError, IndexError):
                        print("Eingabe: Zeile Spalte (z.B. '3 5')")
                        input("Enter drücken...")
            else:
                # Warte auf Gegner-Schuss
                msg = self.wait_msg(["shot_result", "opponent_left"])
                if msg["type"] == "opponent_left":
                    break
                self.process_shot_result(msg)

        self.running = False
        print("\nSpiel beendet. Drücke Enter.")
        input()

    def process_shot_result(self, msg):
        if msg["type"] == "opponent_left":
            print("[!] Gegner hat das Spiel verlassen.")
            self.running = False
            return

        row, col = msg["row"], msg["col"]
        hit = msg["hit"]
        sunk = msg["sunk"]
        your_shot = msg["your_shot"]
        won = msg["won"]

        if your_shot:
            if hit:
                self.enemy_board[row][col] = "X"
                status = "TREFFER!"
                if sunk:
                    status = "VERSENKT!"
            else:
                self.enemy_board[row][col] = "O"
                status = "Wasser."
                self.my_turn = False

            if won:
                clear()
                print_boards(self.my_board, self.enemy_board, self.my_ships, self.my_hits_recv)
                print(f"\n*** Du hast gewonnen! Alle Schiffe von {self.opponent_name} versenkt! ***")
                input("Enter drücken...")
                self.running = False
                return

            if hit:
                self.my_turn = True
            print(f"[Dein Schuss ({row},{col})]: {status}")
        else:
            if hit:
                self.my_board[row][col] = "X"
                self.my_hits_recv.append([row, col])
                status = f"{self.opponent_name} trifft!"
                if sunk:
                    status += " Schiff versenkt!"
            else:
                self.my_board[row][col] = "O"
                status = f"{self.opponent_name}: Wasser."
                self.my_turn = True

            if won:
                clear()
                print_boards(self.my_board, self.enemy_board, self.my_ships, self.my_hits_recv)
                print(f"\n*** {self.opponent_name} hat gewonnen! ***")
                input("Enter drücken...")
                self.running = False
                return


def main():
    clear()
    print("=" * 50)
    print("         SCHIFFEVERSENKEN")
    print("=" * 50)
    print()

    host = input("Server-IP (Enter für localhost): ").strip() or "127.0.0.1"
    port = 5555

    name = ""
    while not name:
        name = input("Dein Name: ").strip()

    print("\n1. Neue Lobby erstellen")
    print("2. Lobby beitreten")
    choice = input("Wahl: ").strip()

    client = GameClient()
    client.name = name

    try:
        client.connect(host, port)
    except Exception as e:
        print(f"Verbindung fehlgeschlagen: {e}")
        sys.exit(1)

    if choice == "1":
        client.send({"action": "create", "name": name})
        msg = client.recv_line()
        if msg["type"] == "error":
            print(f"Fehler: {msg['msg']}")
            sys.exit(1)
        code = msg["code"]
        print(f"\n[*] Lobby erstellt! Code: {code}")
        print("[*] Warte auf Gegner...")

        # Schiffe platzieren während wir warten
        ships = client.place_ships()
        client.send({"type": "place_ships", "ships": ships})
        print("[*] Schiffe platziert. Warte auf Gegner...")

        # Starte recv thread
        threading.Thread(target=client.recv_thread, daemon=True).start()

        # Warte auf opponent_joined und dann game_start
        msg = client.wait_msg(["opponent_joined", "game_start", "waiting_for_opponent"])
        if msg["type"] == "opponent_joined":
            client.opponent_name = msg["opponent"]
            print(f"[*] {client.opponent_name} ist beigetreten!")
            msg = client.wait_msg(["game_start"])

        if msg["type"] == "game_start":
            client.my_turn = msg["your_turn"]
            client.opponent_name = msg.get("opponent", client.opponent_name)
            client.game_loop()

    elif choice == "2":
        code = input("Lobby-Code: ").strip().upper()
        client.send({"action": "join", "name": name, "code": code})
        msg = client.recv_line()
        if msg["type"] == "error":
            print(f"Fehler: {msg['msg']}")
            sys.exit(1)
        client.opponent_name = msg.get("opponent", "Gegner")
        print(f"[*] Lobby beigetreten! Gegner: {client.opponent_name}")

        ships = client.place_ships()
        client.send({"type": "place_ships", "ships": ships})
        print("[*] Schiffe platziert. Warte auf Spielstart...")

        threading.Thread(target=client.recv_thread, daemon=True).start()

        msg = client.wait_msg(["game_start", "waiting_for_opponent"])
        if msg["type"] == "waiting_for_opponent":
            msg = client.wait_msg(["game_start"])

        if msg["type"] == "game_start":
            client.my_turn = msg["your_turn"]
            client.opponent_name = msg.get("opponent", client.opponent_name)
            client.game_loop()
    else:
        print("Ungültige Wahl.")
        sys.exit(1)

    try:
        client.conn.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
