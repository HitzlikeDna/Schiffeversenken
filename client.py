import subprocess
import sys

try:
    import pygame
except ImportError:
    print("Installiere pygame...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--user", "pygame"])
    import pygame

import socket
import threading
import json

# ── Konstanten ──────────────────────────────────────────────────────────────
GRID_SIZE   = 10
CELL        = 46
MARGIN      = 6
GRID_PX     = GRID_SIZE * CELL           # 460

WIN_W       = GRID_PX * 2 + MARGIN * 5  # zwei Felder + Abstände
WIN_H       = GRID_PX + 260             # Felder + UI oben/unten

PORT        = 5555

SHIPS = [
    ("Träger",         5),
    ("Schlachtschiff", 4),
    ("Kreuzer",        3),
    ("U-Boot",         3),
    ("Zerstörer",      2),
]

# ── Farben ───────────────────────────────────────────────────────────────────
C_BG        = (15,  25,  50)
C_WATER     = (30,  80, 160)
C_WATER_H   = (50, 120, 220)   # hover
C_SHIP      = (100, 130, 160)
C_SHIP_PL   = (60, 180, 100)   # preview beim Platzieren
C_SHIP_BAD  = (200,  60,  60)  # ungültige preview
C_HIT       = (220,  50,  50)
C_SUNK      = (140,  20,  20)
C_MISS      = (180, 210, 240)
C_GRID_LINE = (20,  50, 100)
C_TEXT      = (220, 230, 255)
C_TEXT_DIM  = (100, 120, 160)
C_ACCENT    = (80,  180, 255)
C_BTN       = (40,  80, 150)
C_BTN_H     = (60, 110, 200)
C_BTN_ACT   = (30, 140, 100)
C_INPUT_BG  = (20,  40,  90)
C_INPUT_BD  = (60, 100, 180)
C_PANEL     = (20,  35,  75)
C_NOTIFY    = (255, 200,  50)


def draw_text(surf, text, font, color, x, y, center=False):
    s = font.render(text, True, color)
    if center:
        x -= s.get_width() // 2
    surf.blit(s, (x, y))


def draw_button(surf, rect, text, font, hovered=False, active=False):
    col = C_BTN_ACT if active else (C_BTN_H if hovered else C_BTN)
    pygame.draw.rect(surf, col, rect, border_radius=8)
    pygame.draw.rect(surf, C_ACCENT, rect, 2, border_radius=8)
    cx = rect.x + rect.width // 2
    cy = rect.y + rect.height // 2 - font.get_height() // 2
    draw_text(surf, text, font, C_TEXT, cx, cy, center=True)


def draw_input(surf, rect, text, font, active=False, placeholder=""):
    pygame.draw.rect(surf, C_INPUT_BG, rect, border_radius=6)
    bd = C_ACCENT if active else C_INPUT_BD
    pygame.draw.rect(surf, bd, rect, 2, border_radius=6)
    display = text if text else placeholder
    col = C_TEXT if text else C_TEXT_DIM
    t = font.render(display, True, col)
    surf.blit(t, (rect.x + 10, rect.y + rect.height // 2 - t.get_height() // 2))
    if active and text:
        cx = rect.x + 10 + t.get_width() + 2
        cy = rect.y + 6
        pygame.draw.line(surf, C_ACCENT, (cx, cy), (cx, rect.y + rect.height - 6), 2)


# ── Netzwerk ─────────────────────────────────────────────────────────────────
class Net:
    def __init__(self):
        self.conn   = None
        self.buffer = ""
        self.queue  = []
        self.event  = threading.Event()
        self.alive  = True

    def connect(self, host, port):
        self.conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.conn.connect((host, port))
        threading.Thread(target=self._recv_loop, daemon=True).start()

    def send(self, data):
        self.conn.sendall((json.dumps(data) + "\n").encode())

    def _recv_loop(self):
        while self.alive:
            try:
                data = self.conn.recv(4096).decode()
                if not data:
                    raise ConnectionError()
                self.buffer += data
                while "\n" in self.buffer:
                    line, self.buffer = self.buffer.split("\n", 1)
                    self.queue.append(json.loads(line))
                    self.event.set()
            except Exception:
                self.alive = False
                self.event.set()
                break

    def poll(self):
        msgs, self.queue = self.queue[:], []
        return msgs

    def close(self):
        self.alive = False
        try:
            self.conn.close()
        except Exception:
            pass


# ── Spielzustand ─────────────────────────────────────────────────────────────
class State:
    def __init__(self):
        self.my_board    = [["~"] * GRID_SIZE for _ in range(GRID_SIZE)]
        self.enemy_board = [["~"] * GRID_SIZE for _ in range(GRID_SIZE)]
        self.my_ships    = []   # list of coord-lists
        self.sunk_enemy  = []   # coord-lists of sunk enemy ships (revealed)
        self.my_turn     = False
        self.name        = ""
        self.opponent    = ""
        self.lobby_code  = ""


# ── Grid-Zeichnen ─────────────────────────────────────────────────────────────
def grid_origin(left_grid):
    top = 110
    if left_grid:
        return MARGIN * 2, top
    else:
        return MARGIN * 3 + GRID_PX, top


def cell_rect(origin, row, col):
    ox, oy = origin
    return pygame.Rect(ox + col * CELL, oy + row * CELL, CELL - 1, CELL - 1)


def draw_grid(surf, board, origin, font_sm, reveal_ships=True,
              hover_cell=None, preview_cells=None, preview_ok=True,
              sunk_coords=None):
    ox, oy = origin
    sunk_coords = sunk_coords or []

    for r in range(GRID_SIZE):
        for c in range(GRID_SIZE):
            rect = cell_rect(origin, r, c)
            val  = board[r][c]

            # Basisfarbe
            if val == "S" and reveal_ships:
                color = C_SHIP
            else:
                color = C_WATER

            # Hover
            if hover_cell == (r, c) and val == "~":
                color = C_WATER_H

            pygame.draw.rect(surf, color, rect, border_radius=3)

            # Inhalt
            if val == "X":
                col_c = C_SUNK if [r, c] in sunk_coords else C_HIT
                pygame.draw.rect(surf, col_c, rect, border_radius=3)
                pygame.draw.line(surf, (255, 255, 255),
                                 rect.topleft, rect.bottomright, 2)
                pygame.draw.line(surf, (255, 255, 255),
                                 rect.topright, rect.bottomleft, 2)
            elif val == "O":
                pygame.draw.rect(surf, C_MISS, rect, border_radius=3)
                cx, cy = rect.centerx, rect.centery
                pygame.draw.circle(surf, C_WATER, (cx, cy), CELL // 5)

        # Gitternetz-Linien
        pygame.draw.line(surf, C_GRID_LINE,
                         (ox, oy + r * CELL), (ox + GRID_PX, oy + r * CELL))
    pygame.draw.line(surf, C_GRID_LINE,
                     (ox, oy + GRID_PX), (ox + GRID_PX, oy + GRID_PX))
    for c in range(GRID_SIZE + 1):
        pygame.draw.line(surf, C_GRID_LINE,
                         (ox + c * CELL, oy), (ox + c * CELL, oy + GRID_PX))

    # Preview beim Platzieren
    if preview_cells:
        col_p = C_SHIP_PL if preview_ok else C_SHIP_BAD
        for (r, c) in preview_cells:
            if 0 <= r < GRID_SIZE and 0 <= c < GRID_SIZE:
                pygame.draw.rect(surf, col_p, cell_rect(origin, r, c),
                                 border_radius=3)

    # Beschriftung
    for i in range(GRID_SIZE):
        lbl = font_sm.render(str(i), True, C_TEXT_DIM)
        surf.blit(lbl, (ox + i * CELL + CELL // 2 - lbl.get_width() // 2,
                        oy - 18))
        surf.blit(lbl, (ox - 18, oy + i * CELL + CELL // 2 - lbl.get_height() // 2))


# ═══════════════════════════════════════════════════════════════════════════════
#  SCREENS
# ═══════════════════════════════════════════════════════════════════════════════

def screen_login(screen, clock, fonts):
    """Gibt (host, name, action, code) zurück oder None bei Quit."""
    f_big, f_med, f_sm = fonts

    fields   = {"ip": "", "name": "", "code": ""}
    focus    = "ip"
    action   = "create"        # "create" | "join"
    error    = ""

    ip_rect   = pygame.Rect(WIN_W // 2 - 180, 180, 360, 44)
    name_rect = pygame.Rect(WIN_W // 2 - 180, 270, 360, 44)
    code_rect = pygame.Rect(WIN_W // 2 - 180, 360, 360, 44)
    btn_c     = pygame.Rect(WIN_W // 2 - 195, 430, 180, 44)
    btn_j     = pygame.Rect(WIN_W // 2 + 15,  430, 180, 44)
    btn_go    = pygame.Rect(WIN_W // 2 - 100, 495, 200, 48)

    while True:
        mx, my = pygame.mouse.get_pos()
        click  = False

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return None
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                click = True
                if ip_rect.collidepoint(mx, my):   focus = "ip"
                if name_rect.collidepoint(mx, my): focus = "name"
                if code_rect.collidepoint(mx, my): focus = "code"
                if btn_c.collidepoint(mx, my):     action = "create"
                if btn_j.collidepoint(mx, my):     action = "join"
                if btn_go.collidepoint(mx, my):
                    host = fields["ip"].strip() or "127.0.0.1"
                    name = fields["name"].strip()
                    code = fields["code"].strip().upper()
                    if not name:
                        error = "Bitte einen Namen eingeben."
                    elif action == "join" and not code:
                        error = "Bitte den Lobby-Code eingeben."
                    else:
                        return host, name, action, code
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_TAB:
                    order = ["ip", "name", "code"]
                    focus = order[(order.index(focus) + 1) % len(order)]
                elif ev.key == pygame.K_BACKSPACE:
                    fields[focus] = fields[focus][:-1]
                elif ev.key == pygame.K_RETURN:
                    pass
                else:
                    if len(fields[focus]) < 30:
                        fields[focus] += ev.unicode

        screen.fill(C_BG)
        draw_text(screen, "SCHIFFEVERSENKEN", f_big, C_ACCENT,
                  WIN_W // 2, 60, center=True)
        draw_text(screen, "Multiplayer", f_sm, C_TEXT_DIM,
                  WIN_W // 2, 105, center=True)

        draw_text(screen, "Server-IP", f_sm, C_TEXT_DIM,
                  ip_rect.x, ip_rect.y - 22)
        draw_input(screen, ip_rect, fields["ip"], f_med,
                   focus == "ip", "127.0.0.1")

        draw_text(screen, "Dein Name", f_sm, C_TEXT_DIM,
                  name_rect.x, name_rect.y - 22)
        draw_input(screen, name_rect, fields["name"], f_med,
                   focus == "name", "z.B. Kapitän Klaus")

        draw_text(screen, "Lobby-Code (nur beim Beitreten)",
                  f_sm, C_TEXT_DIM, code_rect.x, code_rect.y - 22)
        draw_input(screen, code_rect, fields["code"], f_med,
                   focus == "code", "z.B. XKQR")

        draw_button(screen, btn_c, "Lobby erstellen", f_sm,
                    btn_c.collidepoint(mx, my), action == "create")
        draw_button(screen, btn_j, "Lobby beitreten", f_sm,
                    btn_j.collidepoint(mx, my), action == "join")
        draw_button(screen, btn_go, "Verbinden", f_med,
                    btn_go.collidepoint(mx, my))

        if error:
            draw_text(screen, error, f_sm, C_HIT,
                      WIN_W // 2, 555, center=True)

        pygame.display.flip()
        clock.tick(60)


def screen_place_ships(screen, clock, fonts, state):
    """Gibt placed_ships-Liste zurück oder None bei Quit."""
    f_big, f_med, f_sm = fonts

    board       = [["~"] * GRID_SIZE for _ in range(GRID_SIZE)]
    placed      = []          # [{name, coords}]
    ship_idx    = 0
    direction   = "h"
    origin      = grid_origin(True)
    ox, oy      = origin

    btn_rot = pygame.Rect(WIN_W // 2 + 20, WIN_H - 60, 160, 40)
    btn_rst = pygame.Rect(WIN_W // 2 + 200, WIN_H - 60, 160, 40)

    while ship_idx < len(SHIPS):
        ship_name, length = SHIPS[ship_idx]
        mx, my = pygame.mouse.get_pos()

        # Hover-Zelle berechnen
        col_h = (mx - ox) // CELL
        row_h = (my - oy) // CELL
        hover = (row_h, col_h) if 0 <= row_h < GRID_SIZE and 0 <= col_h < GRID_SIZE else None

        # Preview
        preview, preview_ok = [], True
        if hover:
            for i in range(length):
                r = hover[0] + (i if direction == "v" else 0)
                c = hover[1] + (i if direction == "h" else 0)
                preview.append((r, c))
            for r, c in preview:
                if not (0 <= r < GRID_SIZE and 0 <= c < GRID_SIZE):
                    preview_ok = False
                elif board[r][c] == "S":
                    preview_ok = False
            # Nachbarschaftsprüfung
            if preview_ok:
                for r, c in preview:
                    for dr in [-1, 0, 1]:
                        for dc in [-1, 0, 1]:
                            nr, nc = r + dr, c + dc
                            if 0 <= nr < GRID_SIZE and 0 <= nc < GRID_SIZE:
                                if board[nr][nc] == "S" and (nr, nc) not in [(x[0], x[1]) for x in preview]:
                                    preview_ok = False

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return None
            if ev.type == pygame.KEYDOWN:
                if ev.key in (pygame.K_r, pygame.K_SPACE):
                    direction = "v" if direction == "h" else "h"
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if btn_rot.collidepoint(mx, my):
                    direction = "v" if direction == "h" else "h"
                elif btn_rst.collidepoint(mx, my):
                    board    = [["~"] * GRID_SIZE for _ in range(GRID_SIZE)]
                    placed   = []
                    ship_idx = 0
                elif hover and preview and preview_ok:
                    coords = [[r, c] for r, c in preview]
                    for r, c in coords:
                        board[r][c] = "S"
                    placed.append({"name": ship_name, "coords": coords})
                    state.my_ships.append(coords)
                    ship_idx += 1

        screen.fill(C_BG)
        draw_text(screen, "SCHIFFE PLATZIEREN", f_big, C_ACCENT,
                  WIN_W // 2, 18, center=True)

        # Schiff-Liste rechts
        rx = MARGIN * 3 + GRID_PX + 10
        draw_text(screen, "Schiffe:", f_sm, C_TEXT_DIM, rx, 115)
        for i, (sn, sl) in enumerate(SHIPS):
            done = i < ship_idx
            cur  = i == ship_idx
            col  = C_ACCENT if cur else (C_TEXT_DIM if not done else C_BTN_ACT)
            prefix = "▶ " if cur else ("✓ " if done else "  ")
            draw_text(screen, f"{prefix}{sn} ({sl})", f_sm, col, rx, 140 + i * 30)

        richt_txt = f"Richtung: {'Horizontal →' if direction == 'h' else 'Vertikal ↓'}  (R/Leertaste)"
        draw_text(screen, richt_txt, f_sm, C_TEXT, MARGIN * 2 + 5, WIN_H - 95)

        if ship_idx < len(SHIPS):
            sn, sl = SHIPS[ship_idx]
            draw_text(screen, f"Platziere: {sn}  (Länge {sl})",
                      f_med, C_NOTIFY, MARGIN * 2, WIN_H - 125)

        draw_grid(screen, board, origin, f_sm, reveal_ships=True,
                  hover_cell=hover, preview_cells=preview, preview_ok=preview_ok)

        draw_button(screen, btn_rot, "Drehen (R)", f_sm,
                    btn_rot.collidepoint(mx, my))
        draw_button(screen, btn_rst, "Neu starten", f_sm,
                    btn_rst.collidepoint(mx, my))

        pygame.display.flip()
        clock.tick(60)

    state.my_board = board
    return placed


def screen_waiting(screen, clock, fonts, code, msg_line="Warte auf Gegner…"):
    f_big, f_med, f_sm = fonts
    screen.fill(C_BG)
    draw_text(screen, "LOBBY", f_big, C_ACCENT, WIN_W // 2, 180, center=True)
    draw_text(screen, "Lobby-Code:", f_med, C_TEXT_DIM, WIN_W // 2, 260, center=True)

    # Großer Code
    f_code = pygame.font.SysFont("consolas", 72, bold=True)
    draw_text(screen, code, f_code, C_NOTIFY, WIN_W // 2, 300, center=True)
    draw_text(screen, "Diesen Code an deinen Gegner schicken.",
              f_sm, C_TEXT_DIM, WIN_W // 2, 395, center=True)
    draw_text(screen, msg_line, f_med, C_TEXT, WIN_W // 2, 450, center=True)
    pygame.display.flip()


def screen_game(screen, clock, fonts, net, state):
    f_big, f_med, f_sm = fonts

    origin_mine  = grid_origin(True)
    origin_enemy = grid_origin(False)

    chat_msgs   = []      # (text, color)
    chat_input  = ""
    chat_focus  = False
    chat_rect   = pygame.Rect(MARGIN * 2, WIN_H - 44, WIN_W - MARGIN * 4 - 110, 36)
    send_rect   = pygame.Rect(WIN_W - MARGIN * 2 - 104, WIN_H - 44, 100, 36)

    notification      = ""
    notification_timer = 0

    sunk_enemy_cells = []   # alle Zellen von versenkten Gegnerschiffen

    def add_chat(text, color=C_TEXT):
        chat_msgs.append((text, color))
        if len(chat_msgs) > 6:
            chat_msgs.pop(0)

    def show_notify(text):
        nonlocal notification, notification_timer
        notification = text
        notification_timer = 180   # frames

    def process_msg(msg):
        nonlocal sunk_enemy_cells
        t = msg.get("type")

        if t == "shot_result":
            row, col  = msg["row"], msg["col"]
            hit       = msg["hit"]
            sunk      = msg["sunk"]
            your_shot = msg["your_shot"]
            won       = msg["won"]

            if your_shot:
                if hit:
                    state.enemy_board[row][col] = "X"
                    if sunk:
                        show_notify("SCHIFF VERSENKT!")
                        add_chat("Du hast ein Schiff versenkt!", C_NOTIFY)
                        # Markiere alle Zellen dieses Schiffs
                        sunk_enemy_cells.append([row, col])
                    else:
                        show_notify("TREFFER!")
                        add_chat(f"Treffer auf ({row},{col})!", C_ACCENT)
                    state.my_turn = True
                else:
                    state.enemy_board[row][col] = "O"
                    show_notify("Wasser.")
                    add_chat(f"Verfehlt ({row},{col}).", C_TEXT_DIM)
                    state.my_turn = False

                if won:
                    return "won"

            else:
                if hit:
                    state.my_board[row][col] = "X"
                    if sunk:
                        show_notify(f"{state.opponent} versenkt ein Schiff!")
                        add_chat(f"{state.opponent} versenkt dein Schiff!", C_HIT)
                    else:
                        add_chat(f"{state.opponent} trifft ({row},{col})!", C_HIT)
                    state.my_turn = False
                else:
                    state.my_board[row][col] = "O"
                    add_chat(f"{state.opponent} verfehlt ({row},{col}).", C_TEXT_DIM)
                    state.my_turn = True

                if won:
                    return "lost"

        elif t == "chat":
            add_chat(f"{msg['from']}: {msg['msg']}", C_TEXT)

        elif t == "opponent_left":
            add_chat("Gegner hat das Spiel verlassen.", C_HIT)
            show_notify("Gegner getrennt!")
            return "left"

        return None

    add_chat("Spiel gestartet!", C_BTN_ACT)
    if state.my_turn:
        add_chat("Du beginnst!", C_ACCENT)
    else:
        add_chat(f"{state.opponent} beginnt.", C_TEXT_DIM)

    result = None

    while True:
        mx, my = pygame.mouse.get_pos()
        ox_e, oy_e = origin_enemy

        # Hover auf Gegnergitter
        col_h = (mx - ox_e) // CELL
        row_h = (my - oy_e) // CELL
        ehover = (row_h, col_h) if (0 <= row_h < GRID_SIZE and
                                    0 <= col_h < GRID_SIZE and
                                    state.enemy_board[row_h][col_h] == "~") else None

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                net.close()
                return "quit"

            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if chat_rect.collidepoint(mx, my):
                    chat_focus = True
                elif send_rect.collidepoint(mx, my):
                    if chat_input.strip():
                        net.send({"type": "chat", "msg": chat_input.strip()})
                        add_chat(f"Du: {chat_input.strip()}", C_TEXT_DIM)
                        chat_input = ""
                else:
                    chat_focus = False
                    # Schuss
                    if state.my_turn and ehover and result is None:
                        r, c = ehover
                        net.send({"type": "shoot", "row": r, "col": c})
                        state.my_turn = False

            if ev.type == pygame.KEYDOWN:
                if chat_focus:
                    if ev.key == pygame.K_RETURN:
                        if chat_input.strip():
                            net.send({"type": "chat", "msg": chat_input.strip()})
                            add_chat(f"Du: {chat_input.strip()}", C_TEXT_DIM)
                            chat_input = ""
                    elif ev.key == pygame.K_BACKSPACE:
                        chat_input = chat_input[:-1]
                    else:
                        if len(chat_input) < 60:
                            chat_input += ev.unicode
                else:
                    if ev.key == pygame.K_ESCAPE and result:
                        return result

        # Netzwerk-Nachrichten
        for msg in net.poll():
            r = process_msg(msg)
            if r:
                result = r

        # ── Zeichnen ──────────────────────────────────────────────────────────
        screen.fill(C_BG)

        # Header
        pygame.draw.rect(screen, C_PANEL, (0, 0, WIN_W, 105))
        draw_text(screen, "SCHIFFEVERSENKEN", f_big, C_ACCENT, WIN_W // 2, 8, center=True)
        draw_text(screen, f"Du: {state.name}", f_sm, C_TEXT, 20, 55)
        draw_text(screen, f"Gegner: {state.opponent}", f_sm, C_TEXT, 20, 80)

        if result:
            if result == "won":
                status_txt = "Du hast gewonnen!"
                status_col = C_BTN_ACT
            elif result == "lost":
                status_txt = "Du hast verloren."
                status_col = C_HIT
            else:
                status_txt = "Spiel beendet."
                status_col = C_TEXT_DIM
            draw_text(screen, status_txt, f_med, status_col, WIN_W // 2, 55, center=True)
            draw_text(screen, "ESC zum Schließen", f_sm, C_TEXT_DIM,
                      WIN_W // 2, 82, center=True)
        else:
            if state.my_turn:
                draw_text(screen, ">> DEIN ZUG – Klick auf Gegnergitter <<",
                          f_med, C_NOTIFY, WIN_W // 2, 58, center=True)
            else:
                draw_text(screen, f"Warte auf {state.opponent}…",
                          f_med, C_TEXT_DIM, WIN_W // 2, 58, center=True)

        # Feldtitel
        draw_text(screen, "DEIN FELD", f_sm, C_TEXT_DIM,
                  origin_mine[0] + GRID_PX // 2, 108, center=True)
        draw_text(screen, "GEGNERGITTER", f_sm,
                  C_NOTIFY if state.my_turn else C_TEXT_DIM,
                  origin_enemy[0] + GRID_PX // 2, 108, center=True)

        # Grids
        draw_grid(screen, state.my_board, origin_mine, f_sm, reveal_ships=True)
        draw_grid(screen, state.enemy_board, origin_enemy, f_sm, reveal_ships=False,
                  hover_cell=ehover if state.my_turn else None,
                  sunk_coords=sunk_enemy_cells)

        # Chat-Bereich
        chat_area_y = GRID_PX + 118
        pygame.draw.rect(screen, C_PANEL,
                         (MARGIN * 2, chat_area_y, WIN_W - MARGIN * 4, 85),
                         border_radius=6)
        for i, (ct, cc) in enumerate(chat_msgs[-4:]):
            draw_text(screen, ct, f_sm, cc, MARGIN * 3, chat_area_y + 5 + i * 20)

        draw_input(screen, chat_rect, chat_input, f_sm,
                   chat_focus, "Nachricht eingeben…")
        draw_button(screen, send_rect, "Senden", f_sm,
                    send_rect.collidepoint(mx, my))

        # Notification-Banner
        if notification_timer > 0:
            alpha = min(255, notification_timer * 4)
            s = pygame.Surface((WIN_W, 54), pygame.SRCALPHA)
            s.fill((0, 0, 0, 160))
            screen.blit(s, (0, WIN_H // 2 - 27))
            draw_text(screen, notification, f_big, (*C_NOTIFY, alpha),
                      WIN_W // 2, WIN_H // 2 - 22, center=True)
            notification_timer -= 1

        pygame.display.flip()
        clock.tick(60)


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    pygame.init()
    screen = pygame.display.set_mode((WIN_W, WIN_H))
    pygame.display.set_caption("Schiffeversenken")
    clock  = pygame.time.Clock()

    f_big = pygame.font.SysFont("consolas", 28, bold=True)
    f_med = pygame.font.SysFont("consolas", 20)
    f_sm  = pygame.font.SysFont("consolas", 15)
    fonts = (f_big, f_med, f_sm)

    # ── Login ────────────────────────────────────────────────────────────────
    result = screen_login(screen, clock, fonts)
    if result is None:
        pygame.quit()
        return
    host, name, action, code = result

    # ── Verbinden ────────────────────────────────────────────────────────────
    net   = Net()
    state = State()
    state.name = name

    screen.fill(C_BG)
    draw_text(screen, "Verbinde…", f_med, C_TEXT, WIN_W // 2, WIN_H // 2, center=True)
    pygame.display.flip()

    try:
        net.connect(host, PORT)
    except Exception as e:
        screen.fill(C_BG)
        draw_text(screen, f"Verbindung fehlgeschlagen:", f_med, C_HIT,
                  WIN_W // 2, WIN_H // 2 - 30, center=True)
        draw_text(screen, str(e), f_sm, C_TEXT_DIM,
                  WIN_W // 2, WIN_H // 2 + 10, center=True)
        draw_text(screen, "Fenster schließen…", f_sm, C_TEXT_DIM,
                  WIN_W // 2, WIN_H // 2 + 50, center=True)
        pygame.display.flip()
        pygame.time.wait(4000)
        pygame.quit()
        return

    net.send({"action": action, "name": name, "code": code})

    # Warte auf Server-Antwort (blocking kurz, noch kein Thread nötig)
    def recv_direct():
        while True:
            if "\n" in net.buffer:
                line, net.buffer = net.buffer.split("\n", 1)
                return json.loads(line)
            data = net.conn.recv(4096).decode()
            if not data:
                raise ConnectionError()
            net.buffer += data

    # Ersten Response lesen
    net.conn.settimeout(8)
    try:
        first = recv_direct()
    except Exception:
        screen.fill(C_BG)
        draw_text(screen, "Keine Antwort vom Server.", f_med, C_HIT,
                  WIN_W // 2, WIN_H // 2, center=True)
        pygame.display.flip()
        pygame.time.wait(3000)
        pygame.quit()
        return
    net.conn.settimeout(None)

    if first.get("type") == "error":
        screen.fill(C_BG)
        draw_text(screen, first["msg"], f_med, C_HIT,
                  WIN_W // 2, WIN_H // 2, center=True)
        pygame.display.flip()
        pygame.time.wait(3000)
        pygame.quit()
        return

    if action == "create":
        state.lobby_code = first["code"]
    else:
        state.lobby_code = code
        state.opponent   = first.get("opponent", "Gegner")

    # ── Schiffe platzieren ───────────────────────────────────────────────────
    placed = screen_place_ships(screen, clock, fonts, state)
    if placed is None:
        net.close()
        pygame.quit()
        return

    net.send({"type": "place_ships", "ships": placed})

    # ── Warten ───────────────────────────────────────────────────────────────
    # Thread starten für eingehende Nachrichten
    threading.Thread(target=net._recv_loop, daemon=True).start()

    waiting = True
    while waiting:
        screen_waiting(screen, clock, fonts, state.lobby_code)

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                net.close()
                pygame.quit()
                return

        for msg in net.poll():
            t = msg.get("type")
            if t == "opponent_joined":
                state.opponent = msg["opponent"]
                screen_waiting(screen, clock, fonts, state.lobby_code,
                               f"{state.opponent} ist beigetreten!")
                pygame.time.wait(800)
            elif t == "game_start":
                state.my_turn  = msg["your_turn"]
                state.opponent = msg.get("opponent", state.opponent)
                waiting = False
            elif t == "waiting_for_opponent":
                pass

        clock.tick(30)

    # ── Spiel ────────────────────────────────────────────────────────────────
    screen_game(screen, clock, fonts, net, state)

    net.close()
    pygame.quit()


if __name__ == "__main__":
    main()
