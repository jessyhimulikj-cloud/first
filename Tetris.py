# 俄罗斯方块（Tetris）
# 玩法：控制下落的积木方块在棋盘中堆叠，尽量填满一整行以消除得分。
#      连续消除、同时消除多行会获得更高分数，速度会随等级提升而加快。
#      方块从棋盘顶部生成（默认会略高于可见区域），出现无法放置时即 Game Over。
#      若系统支持，将播放基础提示音（消行/落地/失败）。
# 按键：
#   ← / →  左右移动
#   ↓       软降（加速下落）
#   ↑ 或 X  旋转
#   Z       逆时针旋转
#   Space   硬降（瞬间落到底）
#   C       暂存/交换方块（Hold）
#   P       暂停/继续
#   R       重新开始
# 运行：保存为 Tetris.py 后，在命令行执行：python Tetris.py

import turtle
import random
import time
try:
    import winsound
except ImportError:  # 非 Windows 平台
    winsound = None

# ---------------------- 游戏配置 ----------------------
CELL = 24
COLS = 10
ROWS = 20
BORDER = 2

BOARD_WIDTH = COLS * CELL
BOARD_HEIGHT = ROWS * CELL
PANEL_WIDTH = 160
WINDOW_WIDTH = BOARD_WIDTH + PANEL_WIDTH + 40
WINDOW_HEIGHT = BOARD_HEIGHT + 40

DROP_START = 0.6
DROP_MIN = 0.08
LOCK_DELAY = 0.5

# 计分（参考传统规则）
LINE_SCORES = {1: 100, 2: 300, 3: 500, 4: 800}

# 7种四格方块定义（相对坐标）
SHAPES = {
    "I": [(0, 1), (0, 0), (0, -1), (0, -2)],
    "O": [(0, 0), (1, 0), (0, -1), (1, -1)],
    "T": [(-1, 0), (0, 0), (1, 0), (0, -1)],
    "S": [(-1, -1), (0, -1), (0, 0), (1, 0)],
    "Z": [(-1, 0), (0, 0), (0, -1), (1, -1)],
    "J": [(-1, 0), (-1, -1), (0, -1), (1, -1)],
    "L": [(1, 0), (-1, -1), (0, -1), (1, -1)],
}

COLORS = {
    "I": "cyan",
    "O": "gold",
    "T": "purple",
    "S": "green",
    "Z": "red",
    "J": "blue",
    "L": "orange",
}

# ---------------------- 工具函数 ----------------------

def new_bag():
    bag = list(SHAPES.keys())
    random.shuffle(bag)
    return bag


def rotate(coords, clockwise=True):
    if clockwise:
        return [(-y, x) for x, y in coords]
    return [(y, -x) for x, y in coords]


# ---------------------- 游戏主体 ----------------------

class Tetris:
    def __init__(self):
        self.screen = turtle.Screen()
        self.screen.title("Tetris")
        self.screen.setup(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.screen.bgcolor("black")
        self.screen.tracer(0)

        self.drawer = turtle.Turtle(visible=False)
        self.drawer.penup()
        self.drawer.speed(0)

        self.text = turtle.Turtle(visible=False)
        self.text.penup()
        self.text.color("white")

        self.grid = [[None for _ in range(COLS)] for _ in range(ROWS)]
        self.bag = []
        self.next_piece = None
        self.hold_piece = None
        self.hold_used = False
        self.active = None
        self.active_coords = None
        self.active_pos = (COLS // 2, ROWS - 2)

        self.score = 0
        self.lines = 0
        self.level = 1
        self.drop_interval = DROP_START
        self.last_drop = time.time()
        self.lock_start = None
        self.paused = False
        self.game_over = False

        self.setup_controls()
        self.reset_game()
        self.loop()
        turtle.mainloop()

    # ------------------ 绘制 ------------------
    def to_screen(self, col, row):
        x = -BOARD_WIDTH / 2 + col * CELL + CELL / 2
        y = -BOARD_HEIGHT / 2 + row * CELL + CELL / 2
        return x, y

    def draw_block(self, col, row, color):
        x, y = self.to_screen(col, row)
        self.drawer.goto(x - CELL / 2, y - CELL / 2)
        self.drawer.color("gray", color)
        self.drawer.begin_fill()
        for _ in range(4):
            self.drawer.forward(CELL)
            self.drawer.left(90)
        self.drawer.end_fill()

    def draw_board(self):
        self.drawer.clear()
        # 边框
        self.drawer.color("gray")
        self.drawer.goto(-BOARD_WIDTH / 2 - BORDER, -BOARD_HEIGHT / 2 - BORDER)
        self.drawer.pendown()
        for _ in range(2):
            self.drawer.forward(BOARD_WIDTH + BORDER * 2)
            self.drawer.left(90)
            self.drawer.forward(BOARD_HEIGHT + BORDER * 2)
            self.drawer.left(90)
        self.drawer.penup()

        # 固定方块
        for row in range(ROWS):
            for col in range(COLS):
                color = self.grid[row][col]
                if color:
                    self.draw_block(col, row, color)

        # 阴影
        if self.active and not self.game_over:
            ghost = self.hard_drop_position()
            for col, row in ghost:
                self.drawer.goto(*self.to_screen(col, row))
                self.drawer.dot(CELL - 4, "#222222")

        # 当前方块
        if self.active:
            for col, row in self.current_cells():
                self.draw_block(col, row, COLORS[self.active])

        self.draw_panel()
        self.screen.update()

    def draw_panel(self):
        self.text.clear()
        x = BOARD_WIDTH / 2 + 20
        y = BOARD_HEIGHT / 2 - 20
        self.text.goto(x, y)
        self.text.write(f"Score: {self.score}", font=("Arial", 12, "bold"))
        self.text.goto(x, y - 30)
        self.text.write(f"Lines: {self.lines}", font=("Arial", 12, "bold"))
        self.text.goto(x, y - 60)
        self.text.write(f"Level: {self.level}", font=("Arial", 12, "bold"))

        self.text.goto(x, y - 110)
        self.text.write("Next:", font=("Arial", 12, "bold"))
        self.draw_preview(self.next_piece, x + 20, y - 150)

        self.text.goto(x, y - 230)
        self.text.write("Hold:", font=("Arial", 12, "bold"))
        self.draw_preview(self.hold_piece, x + 20, y - 270)

        if self.paused:
            self.text.goto(0, 0)
            self.text.write("PAUSED", align="center", font=("Arial", 20, "bold"))
        if self.game_over:
            self.text.goto(0, 0)
            self.text.write("GAME OVER\nPress R", align="center", font=("Arial", 20, "bold"))

    def draw_preview(self, shape, x, y):
        if not shape:
            return
        coords = SHAPES[shape]
        for dx, dy in coords:
            px = x + dx * CELL
            py = y + dy * CELL
            self.drawer.goto(px, py)
            self.drawer.dot(CELL - 4, COLORS[shape])

    # ------------------ 控制 ------------------
    def setup_controls(self):
        self.screen.listen()
        self.screen.onkey(lambda: self.move(-1), "Left")
        self.screen.onkey(lambda: self.move(1), "Right")
        self.screen.onkey(self.soft_drop, "Down")
        self.screen.onkey(lambda: self.rotate_piece(True), "Up")
        self.screen.onkey(lambda: self.rotate_piece(True), "x")
        self.screen.onkey(lambda: self.rotate_piece(False), "z")
        self.screen.onkey(self.hard_drop, "space")
        self.screen.onkey(self.hold, "c")
        self.screen.onkey(self.toggle_pause, "p")
        self.screen.onkey(self.reset_game, "r")

    # ------------------ 游戏逻辑 ------------------
    def reset_game(self):
        self.grid = [[None for _ in range(COLS)] for _ in range(ROWS)]
        self.bag = new_bag()
        self.next_piece = self.bag.pop()
        self.hold_piece = None
        self.hold_used = False
        self.active_coords = None
        self.score = 0
        self.lines = 0
        self.level = 1
        self.drop_interval = DROP_START
        self.paused = False
        self.game_over = False
        self.lock_start = None
        self.spawn()

    def spawn(self):
        self.active = self.next_piece
        self.active_coords = list(SHAPES[self.active])
        if not self.bag:
            self.bag = new_bag()
        self.next_piece = self.bag.pop()
        self.active_pos = (COLS // 2, ROWS - 2)
        self.hold_used = False
        self.lock_start = None
        if not self.valid(self.current_cells()):
            self.game_over = True
            self.play_sound("gameover")

    def current_cells(self, coords=None, pos=None):
        coords = coords if coords is not None else self.active_coords
        cx, cy = pos if pos is not None else self.active_pos
        return [(cx + x, cy + y) for x, y in coords]

    def valid(self, cells):
        for col, row in cells:
            if col < 0 or col >= COLS or row < 0 or row >= ROWS:
                return False
            if self.grid[row][col]:
                return False
        return True

    def move(self, dx):
        if self.paused or self.game_over:
            return
        cx, cy = self.active_pos
        new_pos = (cx + dx, cy)
        if self.valid(self.current_cells(pos=new_pos)):
            self.active_pos = new_pos
            self.lock_start = None

    def rotate_piece(self, clockwise):
        if self.paused or self.game_over:
            return
        if self.active == "O":
            return
        rotated = rotate(self.active_coords, clockwise)
        kicks = [(0, 0), (-1, 0), (1, 0), (0, 1), (0, -1)]
        for dx, dy in kicks:
            pos = (self.active_pos[0] + dx, self.active_pos[1] + dy)
            if self.valid(self.current_cells(rotated, pos)):
                self.active_coords = rotated
                self.active_pos = pos
                self.lock_start = None
                return

    def soft_drop(self):
        if self.paused or self.game_over:
            return
        if self.drop(True):
            self.lock_start = None

    def hard_drop_position(self):
        cells = self.current_cells()
        pos = self.active_pos
        while True:
            next_pos = (pos[0], pos[1] - 1)
            next_cells = [(c, r - 1) for c, r in cells]
            if not self.valid(next_cells):
                return cells
            pos = next_pos
            cells = next_cells

    def hard_drop(self):
        if self.paused or self.game_over:
            return
        cells = self.hard_drop_position()
        self.active_pos = (self.active_pos[0], min(r for _, r in cells))
        self.lock_start = None
        self.lock_piece()

    def hold(self):
        if self.paused or self.game_over or self.hold_used:
            return
        current = self.active
        if self.hold_piece is None:
            self.hold_piece = current
            self.spawn()
        else:
            self.active = self.hold_piece
            self.hold_piece = current
            self.active_coords = list(SHAPES[self.active])
            self.active_pos = (COLS // 2, ROWS - 2)
            self.lock_start = None
            if not self.valid(self.current_cells()):
                self.game_over = True
                self.play_sound("gameover")
        self.hold_used = True

    def drop(self, manual=False):
        cx, cy = self.active_pos
        new_pos = (cx, cy - 1)
        if self.valid(self.current_cells(pos=new_pos)):
            self.active_pos = new_pos
            if manual:
                self.score += 1
            return True
        if self.lock_start is None:
            self.lock_start = time.time()
            return False
        if time.time() - self.lock_start >= LOCK_DELAY:
            self.lock_piece()
        return False

    def lock_piece(self):
        for col, row in self.current_cells():
            if 0 <= row < ROWS:
                self.grid[row][col] = COLORS[self.active]
        self.play_sound("lock")
        cleared = self.clear_lines()
        if cleared:
            self.score += LINE_SCORES.get(cleared, cleared * 200) * self.level
            self.lines += cleared
            self.play_sound("clear")
            if self.lines // 10 + 1 > self.level:
                self.level += 1
                self.drop_interval = max(DROP_MIN, DROP_START - (self.level - 1) * 0.05)
        self.spawn()

    def clear_lines(self):
        new_grid = [row for row in self.grid if any(cell is None for cell in row)]
        cleared = ROWS - len(new_grid)
        while len(new_grid) < ROWS:
            new_grid.append([None for _ in range(COLS)])
        self.grid = new_grid
        return cleared

    def toggle_pause(self):
        if self.game_over:
            return
        self.paused = not self.paused

    def loop(self):
        if not self.paused and not self.game_over:
            if time.time() - self.last_drop >= self.drop_interval:
                self.drop()
                self.last_drop = time.time()
            if self.is_grounded():
                if self.lock_start is None:
                    self.lock_start = time.time()
                elif time.time() - self.lock_start >= LOCK_DELAY:
                    self.lock_piece()
            else:
                self.lock_start = None
        self.draw_board()
        self.screen.ontimer(self.loop, 16)

    def is_grounded(self):
        return not self.valid([(c, r - 1) for c, r in self.current_cells()])

    def play_sound(self, event):
        if winsound:
            tones = {
                "lock": (440, 40),
                "clear": (660, 80),
                "gameover": (220, 200),
            }
            freq, duration = tones.get(event, (440, 40))
            winsound.Beep(freq, duration)
        elif hasattr(self.screen, "bell"):
            self.screen.bell()


if __name__ == "__main__":
    Tetris()
