# 打飞机空战游戏（单文件版）
# 玩法：控制战机移动并射击来袭敌机，击落敌机得分，避免碰撞或被敌机子弹击中。
#      随着分数提升，敌机数量和速度会增加，还会出现精英敌机与首领。
#      拾取道具可获得多重子弹、护盾或生命值，尽可能坚持更久。
# 按键：
#   ← / →  左右移动
#   ↑ / ↓  上下移动
#   Space  连射开/关
#   Z      单发射击
#   P      暂停/继续
#   R      重新开始
# 运行：保存为 Tetris.py 后，在命令行执行：python Tetris.py

import turtle
import random
import time

# ---------------------- 基础配置 ----------------------
WIDTH = 520
HEIGHT = 720
HALF_W = WIDTH // 2
HALF_H = HEIGHT // 2

PLAYER_SPEED = 8
BULLET_SPEED = 12
ENEMY_SPEED = 2.4
ELITE_SPEED = 3.0
BOSS_SPEED = 1.5

BULLET_COOLDOWN = 0.14
ELITE_FIRE_COOLDOWN = 1.1
BOSS_FIRE_COOLDOWN = 0.55

MAX_LIVES = 3
HIT_INVULN = 1.2

MAX_PLAYER_BULLETS = 28
MAX_ENEMY_BULLETS = 24
MAX_ENEMIES = 18
MAX_POWERUPS = 6

# ---------------------- 工具函数 ----------------------

def clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def rand_pos_x():
    return random.randint(-HALF_W + 40, HALF_W - 40)


def rand_pos_y():
    return random.randint(80, HALF_H - 40)


def distance(a, b):
    return ((a.xcor() - b.xcor()) ** 2 + (a.ycor() - b.ycor()) ** 2) ** 0.5


def make_turtle(shape, color, scale):
    t = turtle.Turtle(shape)
    t.shapesize(scale, scale)
    t.color(color)
    t.penup()
    t.hideturtle()
    return t


# ---------------------- 游戏主体 ----------------------

class AirCombat:
    def __init__(self):
        self.screen = turtle.Screen()
        self.screen.title("打飞机空战")
        self.screen.setup(WIDTH, HEIGHT)
        self.screen.bgcolor("black")
        self.screen.tracer(0)

        self.hud = turtle.Turtle(visible=False)
        self.hud.penup()
        self.hud.color("white")

        self.player = make_turtle("triangle", "cyan", 1.3)
        self.player.setheading(90)
        self.player.goto(0, -HALF_H + 60)
        self.player.showturtle()

        self.bullets = self.build_pool(MAX_PLAYER_BULLETS, "circle", "yellow", 0.35)
        self.enemy_bullets = self.build_pool(MAX_ENEMY_BULLETS, "circle", "pink", 0.45)
        self.enemies = self.build_pool(MAX_ENEMIES, "square", "red", 1.1)
        self.powerups = self.build_pool(MAX_POWERUPS, "circle", "gold", 0.7)

        self.last_shot = 0
        self.auto_fire = False

        self.score = 0
        self.lives = MAX_LIVES
        self.level = 1
        self.paused = False
        self.game_over = False
        self.shield_timer = 0
        self.multi_timer = 0
        self.invuln_timer = 0
        self.boss = None
        self.boss_hp = 0
        self.last_enemy_shot = time.time()
        self.last_boss_shot = time.time()

        self.setup_controls()
        self.reset_game()
        self.loop()
        turtle.mainloop()

    # ------------------ 池管理 ------------------
    def build_pool(self, count, shape, color, scale):
        return [make_turtle(shape, color, scale) for _ in range(count)]

    def get_from_pool(self, pool):
        for item in pool:
            if not item.isvisible():
                return item
        return None

    # ------------------ 控制 ------------------
    def setup_controls(self):
        self.screen.listen()
        self.screen.onkey(lambda: self.move_player(-PLAYER_SPEED, 0), "Left")
        self.screen.onkey(lambda: self.move_player(PLAYER_SPEED, 0), "Right")
        self.screen.onkey(lambda: self.move_player(0, PLAYER_SPEED), "Up")
        self.screen.onkey(lambda: self.move_player(0, -PLAYER_SPEED), "Down")
        self.screen.onkey(self.single_shot, "z")
        self.screen.onkey(self.toggle_auto_fire, "space")
        self.screen.onkey(self.toggle_pause, "p")
        self.screen.onkey(self.reset_game, "r")

    def move_player(self, dx, dy):
        if self.paused or self.game_over:
            return
        x = clamp(self.player.xcor() + dx, -HALF_W + 20, HALF_W - 20)
        y = clamp(self.player.ycor() + dy, -HALF_H + 40, HALF_H - 40)
        self.player.goto(x, y)

    def toggle_auto_fire(self):
        if self.game_over:
            return
        self.auto_fire = not self.auto_fire

    def single_shot(self):
        if self.paused or self.game_over:
            return
        self.fire_player_bullet()

    def toggle_pause(self):
        if self.game_over:
            return
        self.paused = not self.paused

    # ------------------ 初始化/重置 ------------------
    def reset_game(self):
        self.score = 0
        self.lives = MAX_LIVES
        self.level = 1
        self.paused = False
        self.game_over = False
        self.shield_timer = 0
        self.multi_timer = 0
        self.invuln_timer = 0
        self.boss = None
        self.boss_hp = 0
        self.auto_fire = False
        self.player.goto(0, -HALF_H + 60)
        self.player.color("cyan")

        for pool in (self.bullets, self.enemy_bullets, self.enemies, self.powerups):
            for item in pool:
                item.hideturtle()

        self.spawn_wave()

    # ------------------ 生成/发射 ------------------
    def spawn_enemy(self, elite=False):
        enemy = self.get_from_pool(self.enemies)
        if not enemy:
            return
        enemy.color("orange" if elite else "red")
        enemy.elite = elite
        enemy.goto(rand_pos_x(), rand_pos_y())
        enemy.setheading(270)
        enemy.showturtle()

    def spawn_wave(self):
        base = 4 + min(6, self.level)
        for _ in range(base):
            self.spawn_enemy(elite=False)
        if self.level >= 3:
            for _ in range(max(1, self.level // 3)):
                self.spawn_enemy(elite=True)
        if self.level % 5 == 0:
            self.spawn_boss()

    def spawn_boss(self):
        if self.boss:
            return
        self.boss = make_turtle("circle", "purple", 2.2)
        self.boss.goto(0, HALF_H - 80)
        self.boss.setheading(270)
        self.boss.showturtle()
        self.boss_hp = 14 + self.level * 2

    def fire_player_bullet(self):
        now = time.time()
        if now - self.last_shot < BULLET_COOLDOWN:
            return
        self.last_shot = now
        spread = [-10, 0, 10] if self.multi_timer > 0 else [0]
        for offset in spread:
            bullet = self.get_from_pool(self.bullets)
            if not bullet:
                continue
            bullet.color("yellow")
            bullet.goto(self.player.xcor() + offset, self.player.ycor() + 10)
            bullet.setheading(90)
            bullet.showturtle()

    def fire_enemy_bullet(self, enemy):
        bullet = self.get_from_pool(self.enemy_bullets)
        if not bullet:
            return
        bullet.color("white" if enemy.elite else "pink")
        bullet.goto(enemy.xcor(), enemy.ycor() - 10)
        bullet.setheading(270)
        bullet.showturtle()

    def fire_boss_bullet(self):
        if not self.boss:
            return
        for angle in (-20, 0, 20):
            bullet = self.get_from_pool(self.enemy_bullets)
            if not bullet:
                continue
            bullet.color("violet")
            bullet.goto(self.boss.xcor(), self.boss.ycor() - 20)
            bullet.setheading(270 + angle)
            bullet.showturtle()

    def spawn_powerup(self, kind):
        pu = self.get_from_pool(self.powerups)
        if not pu:
            return
        color = "green" if kind == "life" else "deepskyblue" if kind == "shield" else "gold"
        pu.color(color)
        pu.kind = kind
        pu.goto(rand_pos_x(), rand_pos_y())
        pu.showturtle()

    # ------------------ 更新循环 ------------------
    def loop(self):
        if not self.paused and not self.game_over:
            self.update_timers()
            if self.auto_fire:
                self.fire_player_bullet()
            self.update_bullets()
            self.update_enemies()
            self.update_powerups()
            self.check_collisions()
            self.check_level_progress()
        self.draw_hud()
        self.screen.update()
        self.screen.ontimer(self.loop, 16)

    def update_timers(self):
        if self.shield_timer > 0:
            self.shield_timer = max(0, self.shield_timer - 0.016)
        if self.multi_timer > 0:
            self.multi_timer = max(0, self.multi_timer - 0.016)
        if self.invuln_timer > 0:
            self.invuln_timer = max(0, self.invuln_timer - 0.016)
            if int(self.invuln_timer * 10) % 2 == 0:
                self.player.color("gray")
            else:
                self.player.color("cyan")
        else:
            self.player.color("cyan")

    def update_bullets(self):
        for bullet in self.bullets:
            if not bullet.isvisible():
                continue
            bullet.sety(bullet.ycor() + BULLET_SPEED)
            if bullet.ycor() > HALF_H:
                bullet.hideturtle()

        for bullet in self.enemy_bullets:
            if not bullet.isvisible():
                continue
            bullet.sety(bullet.ycor() - BULLET_SPEED * 0.75)
            if bullet.ycor() < -HALF_H:
                bullet.hideturtle()

    def update_enemies(self):
        for enemy in self.enemies:
            if not enemy.isvisible():
                continue
            speed = ELITE_SPEED if enemy.elite else ENEMY_SPEED
            enemy.sety(enemy.ycor() - speed)
            if enemy.ycor() < -HALF_H + 60:
                enemy.goto(rand_pos_x(), rand_pos_y())

            if enemy.elite and time.time() - self.last_enemy_shot > ELITE_FIRE_COOLDOWN:
                self.fire_enemy_bullet(enemy)
                self.last_enemy_shot = time.time()

        if self.boss:
            self.boss.setx(self.boss.xcor() + random.choice([-1, 1]) * BOSS_SPEED)
            self.boss.setx(clamp(self.boss.xcor(), -HALF_W + 80, HALF_W - 80))
            if time.time() - self.last_boss_shot > BOSS_FIRE_COOLDOWN:
                self.fire_boss_bullet()
                self.last_boss_shot = time.time()

    def update_powerups(self):
        for pu in self.powerups:
            if not pu.isvisible():
                continue
            pu.sety(pu.ycor() - 1.6)
            if pu.ycor() < -HALF_H:
                pu.hideturtle()

    def check_collisions(self):
        for bullet in self.bullets:
            if not bullet.isvisible():
                continue
            for enemy in self.enemies:
                if not enemy.isvisible():
                    continue
                if distance(bullet, enemy) < 18:
                    bullet.hideturtle()
                    enemy.hideturtle()
                    self.score += 10 if not enemy.elite else 20
                    if random.random() < 0.12:
                        self.spawn_powerup(random.choice(["life", "shield", "multi"]))
                    break

            if self.boss and bullet.isvisible() and distance(bullet, self.boss) < 35:
                bullet.hideturtle()
                self.boss_hp -= 1
                self.score += 5
                if self.boss_hp <= 0:
                    self.boss.hideturtle()
                    self.boss = None
                    self.score += 200

        if self.invuln_timer <= 0:
            for bullet in self.enemy_bullets:
                if not bullet.isvisible():
                    continue
                if distance(bullet, self.player) < 18:
                    bullet.hideturtle()
                    self.take_damage()
                    break

            for enemy in self.enemies:
                if not enemy.isvisible():
                    continue
                if distance(enemy, self.player) < 24:
                    enemy.goto(rand_pos_x(), rand_pos_y())
                    self.take_damage()
                    break

            if self.boss and distance(self.boss, self.player) < 45:
                self.take_damage()

        for pu in self.powerups:
            if not pu.isvisible():
                continue
            if distance(pu, self.player) < 20:
                kind = pu.kind
                pu.hideturtle()
                if kind == "life":
                    self.lives = min(MAX_LIVES, self.lives + 1)
                elif kind == "shield":
                    self.shield_timer = 4.0
                elif kind == "multi":
                    self.multi_timer = 5.0

    def take_damage(self):
        if self.shield_timer > 0:
            return
        self.lives -= 1
        self.invuln_timer = HIT_INVULN
        if self.lives <= 0:
            self.game_over = True

    def check_level_progress(self):
        if self.score // 200 + 1 > self.level:
            self.level += 1
            self.spawn_wave()

    # ------------------ HUD ------------------
    def draw_hud(self):
        self.hud.clear()
        self.hud.goto(-HALF_W + 20, HALF_H - 40)
        self.hud.write(
            f"Score: {self.score}  Lives: {self.lives}  Level: {self.level}",
            font=("Arial", 12, "bold"),
        )
        self.hud.goto(-HALF_W + 20, HALF_H - 65)
        self.hud.write(
            f"AutoFire: {'ON' if self.auto_fire else 'OFF'}  Shield: {self.shield_timer:.1f}s  Multi: {self.multi_timer:.1f}s",
            font=("Arial", 10, "normal"),
        )
        if self.boss:
            self.hud.goto(-HALF_W + 20, HALF_H - 90)
            self.hud.write(f"Boss HP: {self.boss_hp}", font=("Arial", 10, "bold"))
        if self.paused:
            self.hud.goto(0, 0)
            self.hud.write("PAUSED", align="center", font=("Arial", 20, "bold"))
        if self.game_over:
            self.hud.goto(0, 0)
            self.hud.write("GAME OVER\nPress R", align="center", font=("Arial", 20, "bold"))


if __name__ == "__main__":
    AirCombat()
