import socket
import threading
import json
import random
import string

HOST = "0.0.0.0"
PORT = 5555

lobbies = {}  # lobby_code -> Lobby
lock = threading.Lock()

SHIPS = [5, 4, 3, 3, 2]
GRID_SIZE = 10


def generate_code():
    return "".join(random.choices(string.ascii_uppercase, k=4))


class Player:
    def __init__(self, conn, addr, name):
        self.conn = conn
        self.addr = addr
        self.name = name
        self.board = [["~"] * GRID_SIZE for _ in range(GRID_SIZE)]
        self.ships = []
        self.ready = False
        self.hits_received = []

    def send(self, data):
        try:
            msg = json.dumps(data) + "\n"
            self.conn.sendall(msg.encode())
        except Exception:
            pass


class Lobby:
    def __init__(self, code):
        self.code = code
        self.players = []
        self.started = False
        self.turn = 0  # index into players

    def broadcast(self, data, exclude=None):
        for p in self.players:
            if p is not exclude:
                p.send(data)

    def other(self, player):
        return next((p for p in self.players if p is not player), None)

    def current_player(self):
        return self.players[self.turn % 2]

    def next_turn(self):
        self.turn += 1


def parse_placement(ships_data):
    placed = []
    for ship in ships_data:
        coords = ship["coords"]
        placed.append(coords)
    return placed


def is_hit(ships, row, col):
    for ship in ships:
        if [row, col] in ship:
            return True
    return False


def is_sunk(ships, row, col, hits):
    for ship in ships:
        if [row, col] in ship:
            return all([c in hits for c in ship])
    return False


def all_sunk(ships, hits):
    for ship in ships:
        if not all([c in hits for c in ship]):
            return False
    return True


def handle_client(conn, addr):
    print(f"[+] Verbindung von {addr}")
    conn.settimeout(None)
    buffer = ""
    player = None
    lobby = None

    def recv_line():
        nonlocal buffer
        while True:
            data = conn.recv(4096).decode()
            if not data:
                raise ConnectionError("Client disconnected")
            buffer += data
            if "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                return json.loads(line)

    try:
        # Handshake
        msg = recv_line()
        name = msg.get("name", "Spieler")
        action = msg.get("action")

        player = Player(conn, addr, name)

        with lock:
            if action == "create":
                code = generate_code()
                while code in lobbies:
                    code = generate_code()
                lobby = Lobby(code)
                lobby.players.append(player)
                lobbies[code] = lobby
                player.send({"type": "lobby_created", "code": code})
                print(f"[*] Lobby {code} erstellt von {name}")

            elif action == "join":
                code = msg.get("code", "").upper()
                if code not in lobbies:
                    player.send({"type": "error", "msg": "Lobby nicht gefunden"})
                    return
                lobby = lobbies[code]
                if len(lobby.players) >= 2:
                    player.send({"type": "error", "msg": "Lobby ist voll"})
                    return
                if lobby.started:
                    player.send({"type": "error", "msg": "Spiel läuft bereits"})
                    return
                lobby.players.append(player)
                player.send({"type": "joined", "code": code, "opponent": lobby.players[0].name})
                lobby.players[0].send({"type": "opponent_joined", "opponent": name})
                print(f"[*] {name} trat Lobby {code} bei")
            else:
                player.send({"type": "error", "msg": "Unbekannte Aktion"})
                return

        # Warte auf Schiff-Platzierung
        msg = recv_line()
        assert msg["type"] == "place_ships"
        player.ships = parse_placement(msg["ships"])
        player.ready = True
        player.send({"type": "waiting_for_opponent"})
        print(f"[*] {name} hat Schiffe platziert")

        # Warte bis beide bereit
        while True:
            opponent = lobby.other(player)
            if opponent and opponent.ready:
                break
            threading.Event().wait(0.2)

        # Spiel starten
        with lock:
            if not lobby.started:
                lobby.started = True
                lobby.turn = random.randint(0, 1)
                for i, p in enumerate(lobby.players):
                    p.send({
                        "type": "game_start",
                        "your_turn": (lobby.turn == i),
                        "opponent": lobby.other(p).name
                    })
                print(f"[*] Lobby {lobby.code}: Spiel gestartet, {lobby.players[lobby.turn].name} beginnt")

        # Spielschleife
        while True:
            msg = recv_line()

            if msg["type"] == "shoot":
                row, col = msg["row"], msg["col"]
                opponent = lobby.other(player)

                with lock:
                    if lobby.current_player() is not player:
                        player.send({"type": "error", "msg": "Nicht dein Zug"})
                        continue

                    hit = is_hit(opponent.ships, row, col)
                    sunk = False
                    if hit:
                        opponent.hits_received.append([row, col])
                        sunk = is_sunk(opponent.ships, row, col, opponent.hits_received)

                    won = all_sunk(opponent.ships, opponent.hits_received) if hit else False

                    result = {
                        "type": "shot_result",
                        "row": row, "col": col,
                        "hit": hit, "sunk": sunk,
                        "won": won,
                        "your_shot": True
                    }
                    player.send(result)

                    opp_result = {
                        "type": "shot_result",
                        "row": row, "col": col,
                        "hit": hit, "sunk": sunk,
                        "won": won,
                        "your_shot": False
                    }
                    opponent.send(opp_result)

                    if won:
                        print(f"[*] {player.name} hat gewonnen!")
                        return

                    if not hit:
                        lobby.next_turn()

            elif msg["type"] == "chat":
                opponent = lobby.other(player)
                if opponent:
                    opponent.send({"type": "chat", "from": player.name, "msg": msg["msg"]})

    except Exception as e:
        print(f"[-] Fehler bei {addr}: {e}")
    finally:
        if lobby and player:
            opponent = lobby.other(player)
            if opponent:
                opponent.send({"type": "opponent_left"})
            with lock:
                if player in lobby.players:
                    lobby.players.remove(player)
                if not lobby.players and lobby.code in lobbies:
                    del lobbies[lobby.code]
                    print(f"[*] Lobby {lobby.code if lobby else '?'} gelöscht")
        try:
            conn.close()
        except Exception:
            pass


def main():
    print(f"[*] Server startet auf Port {PORT}...")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT))
        s.listen()
        print(f"[*] Warte auf Verbindungen...")
        while True:
            conn, addr = s.accept()
            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t.start()


if __name__ == "__main__":
    main()
