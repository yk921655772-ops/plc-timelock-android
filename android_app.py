# android_app.py — PLC 集成商时间锁授权工具 安卓版 V1.0
# 框架: KivyMD 1.2.0 + Kivy 2.3.0
# 算法: 直接复用 calculator.py，与 PC 端 100% 一致

import os
import json
import sqlite3
from datetime import datetime
from functools import partial

from kivy.app import App
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.scrollview import ScrollView
from kivy.uix.screenmanager import Screen, ScreenManager, NoTransition
from kivy.properties import (
    StringProperty, BooleanProperty, ListProperty, NumericProperty
)
from kivy.utils import get_color_from_hex
from kivymd.app import MDApp
from kivymd.uix.behaviors import RectangularRippleBehavior
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDRaisedButton, MDFlatButton, MDIconButton
from kivymd.uix.card import MDCard
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.list import OneLineListItem, TwoLineListItem
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.selectioncontrol import MDCheckbox, MDSwitch
from kivymd.uix.snackbar import Snackbar
from kivymd.uix.textfield import MDTextField
from kivymd.uix.bottomnavigation import MDBottomNavigation, MDBottomNavigationItem

from calculator import FormulaCalculator, PRESET_TEMPLATES

# ─── 平台判断 ────────────────────────────────────
try:
    from android.storage import app_storage_path  # type: ignore
    IS_ANDROID = True
except ImportError:
    IS_ANDROID = False

# ─── 中文字体注册 ────────────────────────────────
def _register_font():
    """将 simhei.ttf 注册为全局 Roboto，解决安卓中文乱码"""
    candidates = [
        os.path.join(os.path.dirname(__file__), "simhei.ttf"),
        os.path.join(os.getcwd(), "simhei.ttf"),
        "/data/data/com.industrial.plclock/files/app/simhei.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            LabelBase.register(name="Roboto", fn_regular=path)
            LabelBase.register(name="RobotoMono", fn_regular=path)
            return True
    return False

_register_font()

# ─── 数据目录 ────────────────────────────────────
def _data_dir() -> str:
    if IS_ANDROID:
        return App.get_running_app().user_data_dir
    return os.path.dirname(os.path.abspath(__file__))

# ═══════════════════════════════════════════════
#   数据管理层
# ═══════════════════════════════════════════════
class DataManager:
    """管理公式、设置、日志三类数据的本地持久化"""

    def __init__(self):
        self._dir = None  # 延迟初始化，等 App 启动后调用 init()
        self._db_conn = None

    def init(self):
        self._dir = _data_dir()
        self._init_db()

    # ── 公式 & 设置（JSON）──────────────────────
    @property
    def _json_path(self):
        return os.path.join(self._dir, "app_data.json")

    def _load_json(self) -> dict:
        try:
            with open(self._json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_json(self, data: dict):
        try:
            with open(self._json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def load_settings(self) -> dict:
        d = self._load_json()
        return d.get("settings", {
            "mc_mode": "hex",
            "theme": "Light",
            "font_scale": 1.0,
            "default_tab": "generator",
            "auto_copy": False,
        })

    def save_settings(self, settings: dict):
        d = self._load_json()
        d["settings"] = settings
        self._save_json(d)

    def load_formulas(self) -> list:
        d = self._load_json()
        return d.get("formulas", [])

    def save_formulas(self, formulas: list):
        d = self._load_json()
        d["formulas"] = formulas
        self._save_json(d)

    def load_current_formula(self) -> dict:
        d = self._load_json()
        return d.get("current_formula", {
            "name": "简单模式",
            "formula": "(Y + M + D) * MC",
            "mc_mode": "hex",
        })

    def save_current_formula(self, name: str, formula: str, mc_mode: str):
        d = self._load_json()
        d["current_formula"] = {"name": name, "formula": formula, "mc_mode": mc_mode}
        self._save_json(d)

    # ── 授权日志（SQLite）──────────────────────
    def _init_db(self):
        db_path = os.path.join(self._dir, "auth_log.db")
        self._db_conn = sqlite3.connect(db_path, check_same_thread=False)
        self._db_conn.execute("""
            CREATE TABLE IF NOT EXISTS auth_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                machine_code TEXT,
                formula_name TEXT,
                password TEXT
            )
        """)
        self._db_conn.commit()

    def add_log(self, machine_code: str, formula_name: str, password: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._db_conn.execute(
            "INSERT INTO auth_log (timestamp, machine_code, formula_name, password) VALUES (?,?,?,?)",
            (ts, machine_code, formula_name, password)
        )
        self._db_conn.commit()

    def get_logs(self) -> list:
        cur = self._db_conn.execute(
            "SELECT timestamp, machine_code, formula_name, password FROM auth_log ORDER BY id DESC"
        )
        return [{"ts": r[0], "mc": r[1], "name": r[2], "pw": r[3]} for r in cur.fetchall()]

    def clear_logs(self):
        self._db_conn.execute("DELETE FROM auth_log")
        self._db_conn.commit()

    def export_txt(self) -> str:
        """导出日志为 TXT，返回保存路径"""
        logs = self.get_logs()
        lines = ["时间戳\t\t\t机器码\t公式名称\t\t生成密码\n", "-" * 60 + "\n"]
        for r in logs:
            lines.append(f"{r['ts']}\t{r['mc']}\t{r['name']}\t{r['pw']}\n")
        export_path = os.path.join(self._dir, f"auth_log_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        with open(export_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return export_path


# 全局单例
data_mgr = DataManager()


# ═══════════════════════════════════════════════
#   通用 UI 组件
# ═══════════════════════════════════════════════
def show_toast(msg: str, duration: float = 2.0):
    """显示底部 Snackbar 提示"""
    try:
        Snackbar(text=msg, snackbar_x=dp(8), snackbar_y=dp(8),
                 size_hint_x=0.95, duration=duration).open()
    except Exception:
        pass


def make_section_card(**kwargs) -> MDCard:
    card = MDCard(
        orientation="vertical",
        padding=dp(12),
        spacing=dp(8),
        size_hint_y=None,
        elevation=2,
        radius=[dp(8)],
        **kwargs
    )
    card.bind(minimum_height=card.setter("height"))
    return card


def make_label(text: str, font_size=dp(14), bold=False,
               color=None, halign="left") -> MDLabel:
    lbl = MDLabel(
        text=text,
        font_size=font_size,
        bold=bold,
        halign=halign,
        size_hint_y=None,
        height=dp(32) if not bold else dp(36),
    )
    if color:
        lbl.theme_text_color = "Custom"
        lbl.text_color = color
    lbl.bind(size=lbl.setter("text_size"))
    return lbl


def make_field(hint: str, max_len: int = 0,
               input_filter=None, multiline=False) -> MDTextField:
    f = MDTextField(
        hint_text=hint,
        mode="rectangle",
        size_hint_y=None,
        height=dp(56) if not multiline else dp(100),
        multiline=multiline,
    )
    if max_len:
        f.max_text_length = max_len
    if input_filter:
        f.input_filter = input_filter
    return f


# ═══════════════════════════════════════════════
#   自定义顶部标题栏（替代 MDTopAppBar 避免乱码）
# ═══════════════════════════════════════════════
class CustomTopBar(BoxLayout):
    title_text = StringProperty("PLC 时间锁生成器")
    subtitle_text = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "horizontal"
        self.size_hint_y = None
        self.height = dp(56)
        self.padding = [dp(16), 0, dp(16), 0]
        self.spacing = dp(8)
        self._bg_color = get_color_from_hex("#1976D2")
        self._build()

    def _build(self):
        from kivy.graphics import Color, Rectangle
        with self.canvas.before:
            self._bg = Color(*self._bg_color)
            self._rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._update_rect, size=self._update_rect)

        # 标题
        self._title_lbl = MDLabel(
            text=self.title_text,
            font_size=dp(18),
            bold=True,
            theme_text_color="Custom",
            text_color=(1, 1, 1, 1),
            size_hint_x=0.6,
            valign="center",
        )
        self._title_lbl.bind(size=self._title_lbl.setter("text_size"))

        # 右侧副标题（当前公式名）
        self._sub_lbl = MDLabel(
            text=self.subtitle_text,
            font_size=dp(12),
            theme_text_color="Custom",
            text_color=(1, 1, 1, 0.85),
            size_hint_x=0.4,
            halign="right",
            valign="center",
        )
        self._sub_lbl.bind(size=self._sub_lbl.setter("text_size"))

        self.add_widget(self._title_lbl)
        self.add_widget(self._sub_lbl)

    def _update_rect(self, *_):
        self._rect.pos = self.pos
        self._rect.size = self.size

    def set_subtitle(self, text: str):
        self.subtitle_text = text
        self._sub_lbl.text = text


# ═══════════════════════════════════════════════
#   Tab1 — 密码生成页
# ═══════════════════════════════════════════════
class GeneratorScreen(Screen):
    current_formula_name = StringProperty("简单模式")
    current_formula = StringProperty("(Y + M + D) * MC")
    current_mc_mode = StringProperty("hex")

    def __init__(self, top_bar: CustomTopBar, **kwargs):
        super().__init__(**kwargs)
        self.top_bar = top_bar
        self.calculator = FormulaCalculator()
        self._build_ui()

    def on_enter(self):
        self._refresh_formula_display()

    def _refresh_formula_display(self):
        cf = data_mgr.load_current_formula()
        self.current_formula_name = cf["name"]
        self.current_formula = cf["formula"]
        self.current_mc_mode = cf.get("mc_mode", "hex")
        self.top_bar.set_subtitle(f"当前公式: {self.current_formula_name}")
        self._mc_mode_label.text = f"机器码模式: {'HEX转整数' if self.current_mc_mode == 'hex' else 'ASCII求和'}"

    def _build_ui(self):
        scroll = ScrollView()
        root = MDBoxLayout(
            orientation="vertical",
            padding=dp(16),
            spacing=dp(12),
            size_hint_y=None,
        )
        root.bind(minimum_height=root.setter("height"))

        # ─ 参数输入卡片 ─────────────────────────
        card_input = make_section_card()

        card_input.add_widget(make_label("参数输入", font_size=dp(15), bold=True))

        # 时间 4 宫格
        time_grid = GridLayout(
            cols=4, spacing=dp(8), size_hint_y=None, height=dp(70)
        )
        self.f_year = make_field("年(后2位)", max_len=2, input_filter="int")
        self.f_month = make_field("月", max_len=2, input_filter="int")
        self.f_day = make_field("日", max_len=2, input_filter="int")
        self.f_hour = make_field("时", max_len=2, input_filter="int")
        for f in [self.f_year, self.f_month, self.f_day, self.f_hour]:
            time_grid.add_widget(f)
        card_input.add_widget(time_grid)

        # 字段标签行
        label_grid = GridLayout(cols=4, size_hint_y=None, height=dp(20))
        for t in ["年", "月", "日", "时"]:
            label_grid.add_widget(make_label(t, font_size=dp(12), halign="center"))
        card_input.add_widget(label_grid)

        # 机器码
        self.f_mc = make_field("机器码(4位)", max_len=4)
        self.f_mc.bind(on_text_validate=lambda _: None)
        self.f_mc.bind(text=self._on_mc_text)
        card_input.add_widget(self.f_mc)

        # MC 模式显示 + 切换按钮
        mc_mode_row = MDBoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        self._mc_mode_label = make_label("机器码模式: HEX转整数", font_size=dp(12))
        btn_toggle_mode = MDFlatButton(
            text="切换模式",
            size_hint_x=None,
            width=dp(90),
            on_release=self._toggle_mc_mode,
        )
        mc_mode_row.add_widget(self._mc_mode_label)
        mc_mode_row.add_widget(btn_toggle_mode)
        card_input.add_widget(mc_mode_row)

        # 获取当前时间按钮
        btn_now = MDRaisedButton(
            text="获取当前时间",
            size_hint_y=None,
            height=dp(48),
            on_release=self._fill_current_time,
        )
        card_input.add_widget(btn_now)
        root.add_widget(card_input)

        # ─ 生成结果卡片 ─────────────────────────
        card_result = make_section_card()
        card_result.add_widget(make_label("密码生成", font_size=dp(15), bold=True))

        btn_gen = MDRaisedButton(
            text="生成密码",
            size_hint_y=None,
            height=dp(56),
            md_bg_color=get_color_from_hex("#1976D2"),
            on_release=self._generate,
        )
        card_result.add_widget(btn_gen)

        self.lbl_password = MDLabel(
            text="------",
            font_size=dp(52),
            bold=True,
            halign="center",
            size_hint_y=None,
            height=dp(80),
            theme_text_color="Custom",
            text_color=get_color_from_hex("#D32F2F"),
        )
        self.lbl_password.bind(size=self.lbl_password.setter("text_size"))
        card_result.add_widget(self.lbl_password)

        btn_copy = MDFlatButton(
            text="复制到剪贴板",
            size_hint_y=None,
            height=dp(48),
            on_release=self._copy_password,
        )
        card_result.add_widget(btn_copy)

        self.lbl_status = MDLabel(
            text="",
            font_size=dp(13),
            halign="center",
            size_hint_y=None,
            height=dp(24),
            theme_text_color="Custom",
            text_color=get_color_from_hex("#388E3C"),
        )
        card_result.add_widget(self.lbl_status)
        root.add_widget(card_result)

        scroll.add_widget(root)
        self.add_widget(scroll)

    # ─ 事件处理 ─────────────────────────────────
    def _on_mc_text(self, instance, value):
        upper = "".join(c for c in value.upper() if c in "0123456789ABCDEF")[:4]
        if upper != value:
            instance.text = upper

    def _toggle_mc_mode(self, *_):
        if self.current_mc_mode == "hex":
            self.current_mc_mode = "ascii"
            self._mc_mode_label.text = "机器码模式: ASCII求和"
        else:
            self.current_mc_mode = "hex"
            self._mc_mode_label.text = "机器码模式: HEX转整数"
        data_mgr.save_current_formula(
            self.current_formula_name, self.current_formula, self.current_mc_mode)

    def _fill_current_time(self, *_):
        now = datetime.now()
        self.f_year.text = now.strftime("%y")
        self.f_month.text = now.strftime("%m")
        self.f_day.text = now.strftime("%d")
        self.f_hour.text = now.strftime("%H")

    def _generate(self, *_):
        try:
            Y = int(self.f_year.text or "0")
            M = int(self.f_month.text or "0")
            D = int(self.f_day.text or "0")
            H = int(self.f_hour.text or "0")
        except ValueError:
            show_toast("参数格式错误，年月日时必须为数字")
            return

        mc = self.f_mc.text.strip().upper()
        if len(mc) != 4:
            show_toast("机器码必须为 4 位")
            return

        # 范围校验
        if not (1 <= M <= 12):
            self.f_month.error = True
            show_toast("月份范围: 01 ~ 12")
            return
        if not (1 <= D <= 31):
            self.f_day.error = True
            show_toast("日期范围: 01 ~ 31")
            return
        if not (0 <= H <= 23):
            self.f_hour.error = True
            show_toast("小时范围: 00 ~ 23")
            return

        self.calculator.set_formula(self.current_formula)
        password, err = self.calculator.calculate(Y, M, D, H, mc, self.current_mc_mode)
        if err:
            show_toast(f"计算错误: {err}")
            self.lbl_password.text = "------"
            return

        self.lbl_password.text = password
        self.lbl_status.text = "生成成功"
        Clock.schedule_once(lambda _: setattr(self.lbl_status, "text", ""), 3)

        # 记录日志
        data_mgr.add_log(mc, self.current_formula_name, password)

        # 自动复制
        settings = data_mgr.load_settings()
        if settings.get("auto_copy", False):
            Clipboard.copy(password)
            show_toast("密码已自动复制到剪贴板")

    def _copy_password(self, *_):
        pw = self.lbl_password.text
        if pw == "------":
            show_toast("请先生成密码")
            return
        Clipboard.copy(pw)
        show_toast("密码已复制到剪贴板")

    def get_params(self) -> dict:
        """供 Tab2 验证页读取当前参数"""
        return {
            "year": self.f_year.text,
            "month": self.f_month.text,
            "day": self.f_day.text,
            "hour": self.f_hour.text,
            "mc": self.f_mc.text.upper(),
            "mc_mode": self.current_mc_mode,
            "formula": self.current_formula,
        }


# ═══════════════════════════════════════════════
#   Tab2 — 密码验证页
# ═══════════════════════════════════════════════
class VerifyScreen(Screen):
    def __init__(self, generator: GeneratorScreen, **kwargs):
        super().__init__(**kwargs)
        self.generator = generator
        self.calculator = FormulaCalculator()
        self._build_ui()

    def _build_ui(self):
        scroll = ScrollView()
        root = MDBoxLayout(
            orientation="vertical",
            padding=dp(16),
            spacing=dp(12),
            size_hint_y=None,
        )
        root.bind(minimum_height=root.setter("height"))

        card = make_section_card()
        card.add_widget(make_label("密码验证", font_size=dp(15), bold=True))

        # 使用当前参数开关
        use_cur_row = MDBoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        use_cur_row.add_widget(make_label("使用生成器中的当前参数"))
        self.chk_use_current = MDCheckbox(
            active=True,
            size_hint=(None, None),
            size=(dp(36), dp(36)),
        )
        self.chk_use_current.bind(active=self._on_use_current_changed)
        use_cur_row.add_widget(self.chk_use_current)
        card.add_widget(use_cur_row)

        # 手动参数输入区
        self._manual_fields_container = MDBoxLayout(
            orientation="vertical",
            spacing=dp(8),
            size_hint_y=None,
        )
        self._manual_fields_container.bind(
            minimum_height=self._manual_fields_container.setter("height"))

        tg = GridLayout(cols=4, spacing=dp(8), size_hint_y=None, height=dp(70))
        self.v_year = make_field("年", max_len=2, input_filter="int")
        self.v_month = make_field("月", max_len=2, input_filter="int")
        self.v_day = make_field("日", max_len=2, input_filter="int")
        self.v_hour = make_field("时", max_len=2, input_filter="int")
        for f in [self.v_year, self.v_month, self.v_day, self.v_hour]:
            tg.add_widget(f)
        self._manual_fields_container.add_widget(tg)

        self.v_mc = make_field("机器码(4位)", max_len=4)
        self.v_mc.bind(text=lambda i, v: setattr(i, "text",
            "".join(c for c in v.upper() if c in "0123456789ABCDEF")[:4]))
        self._manual_fields_container.add_widget(self.v_mc)
        self._manual_fields_container.disabled = True
        card.add_widget(self._manual_fields_container)

        # 待验证密码
        self.v_password = make_field("待验证密码(6位)", max_len=6, input_filter="int")
        card.add_widget(self.v_password)

        # 验证按钮
        btn_verify = MDRaisedButton(
            text="开始验证",
            size_hint_y=None,
            height=dp(56),
            md_bg_color=get_color_from_hex("#388E3C"),
            on_release=self._verify,
        )
        card.add_widget(btn_verify)

        # 结果
        self.lbl_result = MDLabel(
            text="",
            font_size=dp(22),
            bold=True,
            halign="center",
            size_hint_y=None,
            height=dp(56),
            theme_text_color="Custom",
            text_color=(0, 0, 0, 0),
        )
        self.lbl_result.bind(size=self.lbl_result.setter("text_size"))
        card.add_widget(self.lbl_result)

        root.add_widget(card)
        scroll.add_widget(root)
        self.add_widget(scroll)

    def _on_use_current_changed(self, instance, value):
        self._manual_fields_container.disabled = value
        if value:
            self._fill_from_generator()

    def _fill_from_generator(self):
        p = self.generator.get_params()
        self.v_year.text = p["year"]
        self.v_month.text = p["month"]
        self.v_day.text = p["day"]
        self.v_hour.text = p["hour"]
        self.v_mc.text = p["mc"]

    def on_enter(self):
        if self.chk_use_current.active:
            self._fill_from_generator()

    def _verify(self, *_):
        if self.chk_use_current.active:
            p = self.generator.get_params()
            try:
                Y, M, D, H = int(p["year"] or "0"), int(p["month"] or "0"), \
                              int(p["day"] or "0"), int(p["hour"] or "0")
            except ValueError:
                show_toast("生成器中的参数无效，请先填写")
                return
            mc = p["mc"]
            mc_mode = p["mc_mode"]
            formula = p["formula"]
        else:
            try:
                Y = int(self.v_year.text or "0")
                M = int(self.v_month.text or "0")
                D = int(self.v_day.text or "0")
                H = int(self.v_hour.text or "0")
            except ValueError:
                show_toast("参数格式错误")
                return
            mc = self.v_mc.text.upper()
            mc_mode = self.generator.current_mc_mode
            formula = self.generator.current_formula

        if len(mc) != 4:
            show_toast("机器码必须为 4 位")
            return

        input_pw = self.v_password.text.strip()
        if len(input_pw) != 6 or not input_pw.isdigit():
            show_toast("请输入完整的 6 位数字密码")
            return

        self.calculator.set_formula(formula)
        calc_pw, err = self.calculator.calculate(Y, M, D, H, mc, mc_mode)
        if err:
            show_toast(f"计算错误: {err}")
            return

        if input_pw == calc_pw:
            self.lbl_result.text = "验证通过"
            self.lbl_result.text_color = get_color_from_hex("#388E3C")
            show_toast("验证通过！密码匹配", 2.0)
        else:
            self.lbl_result.text = f"验证失败 | 正确: {calc_pw}"
            self.lbl_result.text_color = get_color_from_hex("#D32F2F")
            show_toast(f"验证失败，正确密码: {calc_pw}", 3.0)


# ═══════════════════════════════════════════════
#   Tab3 — 更多功能页（公式编辑器 + 日志 + 设置）
# ═══════════════════════════════════════════════
class LogRowItem(MDBoxLayout):
    """日志列表行"""
    ts_text = StringProperty("")
    mc_text = StringProperty("")
    name_text = StringProperty("")
    pw_text = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "horizontal"
        self.size_hint_y = None
        self.height = dp(48)
        self.padding = [dp(4), 0, dp(4), 0]
        self.spacing = dp(4)
        for attr, hint_w in [
            ("ts_text", 0.38), ("mc_text", 0.15),
            ("name_text", 0.27), ("pw_text", 0.2)
        ]:
            lbl = MDLabel(
                font_size=dp(11),
                size_hint_x=hint_w,
                halign="center",
                theme_text_color="Secondary",
            )
            lbl.bind(size=lbl.setter("text_size"))
            self.bind(**{attr: lbl.setter("text")})
            self.add_widget(lbl)


class MoreScreen(Screen):
    def __init__(self, generator: GeneratorScreen, **kwargs):
        super().__init__(**kwargs)
        self.generator = generator
        self.calculator = FormulaCalculator()
        self._saved_formulas = []
        self._build_ui()

    def on_enter(self):
        self._load_saved_formulas()
        self._refresh_log()

    def _build_ui(self):
        scroll = ScrollView()
        root = MDBoxLayout(
            orientation="vertical",
            padding=dp(16),
            spacing=dp(12),
            size_hint_y=None,
        )
        root.bind(minimum_height=root.setter("height"))

        root.add_widget(self._build_formula_card())
        root.add_widget(self._build_log_card())
        root.add_widget(self._build_settings_card())

        scroll.add_widget(root)
        self.add_widget(scroll)

    # ─ 公式编辑器卡片 ────────────────────────────
    def _build_formula_card(self) -> MDCard:
        card = make_section_card()
        card.add_widget(make_label("公式编辑器", font_size=dp(15), bold=True))

        # 说明文字
        hint_text = (
            "[b]可用变量:[/b]  Y=年(后2位)  M=月  D=日  H=时  MC=机器码整数\n"
            "[b]可用运算:[/b]  + - * / // % ** ^ & |\n"
            "[b]可用函数:[/b]  abs() round() pow() min() max() sin() cos() sqrt()"
        )
        hint_lbl = MDLabel(
            text=hint_text,
            markup=True,
            font_size=dp(12),
            size_hint_y=None,
            height=dp(72),
            theme_text_color="Secondary",
        )
        hint_lbl.bind(size=hint_lbl.setter("text_size"))
        card.add_widget(hint_lbl)

        # 预设模板按钮行
        tpl_row = MDBoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        tpl_row.add_widget(make_label("预设模板:"))
        self._tpl_btn = MDFlatButton(
            text="选择预设",
            on_release=self._show_template_menu,
        )
        tpl_row.add_widget(self._tpl_btn)
        card.add_widget(tpl_row)

        # 公式输入框
        self.f_formula = make_field("公式表达式", multiline=True)
        self.f_formula.bind(text=self._on_formula_changed)
        card.add_widget(self.f_formula)

        # 语法检查状态
        self.lbl_syntax = MDLabel(
            text="请输入公式",
            font_size=dp(12),
            size_hint_y=None,
            height=dp(24),
            theme_text_color="Custom",
            text_color=get_color_from_hex("#9E9E9E"),
        )
        card.add_widget(self.lbl_syntax)

        # 公式名称
        self.f_formula_name = make_field("公式名称")
        card.add_widget(self.f_formula_name)

        # 保存 / 加载按钮行
        btn_row = MDBoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        btn_save = MDRaisedButton(
            text="保存公式",
            size_hint_x=0.5,
            on_release=self._save_formula,
        )
        btn_use = MDRaisedButton(
            text="应用到生成器",
            size_hint_x=0.5,
            md_bg_color=get_color_from_hex("#388E3C"),
            on_release=self._apply_to_generator,
        )
        btn_row.add_widget(btn_save)
        btn_row.add_widget(btn_use)
        card.add_widget(btn_row)

        # 已保存公式列表标题
        card.add_widget(make_label("已保存公式列表", font_size=dp(13), bold=True))

        self._formula_list_container = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(4),
        )
        self._formula_list_container.bind(
            minimum_height=self._formula_list_container.setter("height"))
        card.add_widget(self._formula_list_container)

        return card

    def _on_formula_changed(self, instance, value):
        formula = value.strip()
        if not formula:
            self.lbl_syntax.text = "请输入公式"
            self.lbl_syntax.text_color = get_color_from_hex("#9E9E9E")
            return
        valid, msg = self.calculator.validate(formula)
        if valid:
            self.lbl_syntax.text = "✔ " + msg
            self.lbl_syntax.text_color = get_color_from_hex("#388E3C")
        else:
            self.lbl_syntax.text = "✘ " + msg
            self.lbl_syntax.text_color = get_color_from_hex("#D32F2F")

    def _show_template_menu(self, *_):
        items = [
            {"text": t["name"],
             "viewclass": "OneLineListItem",
             "on_release": partial(self._apply_template, t)}
            for t in PRESET_TEMPLATES
        ]
        self._tpl_menu = MDDropdownMenu(
            caller=self._tpl_btn,
            items=items,
            width_mult=4,
        )
        self._tpl_menu.open()

    def _apply_template(self, tpl, *_):
        self.f_formula.text = tpl["formula"]
        self.f_formula_name.text = tpl["name"]
        try:
            self._tpl_menu.dismiss()
        except Exception:
            pass

    def _save_formula(self, *_):
        formula = self.f_formula.text.strip()
        name = self.f_formula_name.text.strip() or "未命名公式"
        if not formula:
            show_toast("公式不能为空")
            return
        valid, msg = self.calculator.validate(formula)
        if not valid:
            show_toast(f"语法错误: {msg}")
            return
        formulas = data_mgr.load_formulas()
        # 名称去重
        formulas = [f for f in formulas if f["name"] != name]
        formulas.append({"name": name, "formula": formula,
                          "mc_mode": self.generator.current_mc_mode})
        data_mgr.save_formulas(formulas)
        self._load_saved_formulas()
        show_toast(f"公式「{name}」已保存")

    def _apply_to_generator(self, *_):
        formula = self.f_formula.text.strip()
        name = self.f_formula_name.text.strip() or "自定义公式"
        if not formula:
            show_toast("请先输入公式")
            return
        valid, msg = self.calculator.validate(formula)
        if not valid:
            show_toast(f"语法错误，无法应用: {msg}")
            return
        mc_mode = self.generator.current_mc_mode
        self.generator.current_formula = formula
        self.generator.current_formula_name = name
        data_mgr.save_current_formula(name, formula, mc_mode)
        self.generator.top_bar.set_subtitle(f"当前公式: {name}")
        show_toast(f"已应用公式: {name}")

    def _load_saved_formulas(self):
        self._saved_formulas = data_mgr.load_formulas()
        self._formula_list_container.clear_widgets()
        if not self._saved_formulas:
            self._formula_list_container.add_widget(
                make_label("暂无保存的公式", font_size=dp(12)))
            return
        for idx, f in enumerate(self._saved_formulas):
            row = MDBoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
            lbl = MDLabel(
                text=f"{f['name']}: {f['formula'][:30]}...",
                font_size=dp(12),
                size_hint_x=0.7,
                theme_text_color="Secondary",
            )
            lbl.bind(size=lbl.setter("text_size"))
            btn_load = MDFlatButton(
                text="加载",
                size_hint_x=0.15,
                on_release=partial(self._load_formula_item, idx),
            )
            btn_del = MDFlatButton(
                text="删除",
                size_hint_x=0.15,
                theme_text_color="Custom",
                text_color=get_color_from_hex("#D32F2F"),
                on_release=partial(self._delete_formula_item, idx),
            )
            row.add_widget(lbl)
            row.add_widget(btn_load)
            row.add_widget(btn_del)
            self._formula_list_container.add_widget(row)

    def _load_formula_item(self, idx, *_):
        if 0 <= idx < len(self._saved_formulas):
            f = self._saved_formulas[idx]
            self.f_formula.text = f["formula"]
            self.f_formula_name.text = f["name"]

    def _delete_formula_item(self, idx, *_):
        if 0 <= idx < len(self._saved_formulas):
            deleted = self._saved_formulas.pop(idx)
            data_mgr.save_formulas(self._saved_formulas)
            self._load_saved_formulas()
            show_toast(f"已删除公式: {deleted['name']}")

    # ─ 授权日志卡片 ──────────────────────────────
    def _build_log_card(self) -> MDCard:
        card = make_section_card()
        card.add_widget(make_label("授权日志", font_size=dp(15), bold=True))

        # 列标题行
        header = MDBoxLayout(size_hint_y=None, height=dp(32), spacing=dp(4))
        for t, w in [("时间", 0.38), ("机器码", 0.15), ("公式", 0.27), ("密码", 0.2)]:
            lbl = make_label(t, font_size=dp(12), bold=True, halign="center")
            lbl.size_hint_x = w
            header.add_widget(lbl)
        card.add_widget(header)

        # 日志列表容器（最多显示最近20条）
        self._log_container = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(2),
        )
        self._log_container.bind(
            minimum_height=self._log_container.setter("height"))
        card.add_widget(self._log_container)

        # 按钮行
        btn_row = MDBoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        btn_export = MDRaisedButton(
            text="导出TXT",
            size_hint_x=0.5,
            on_release=self._export_log,
        )
        btn_clear = MDFlatButton(
            text="清空日志",
            size_hint_x=0.5,
            theme_text_color="Custom",
            text_color=get_color_from_hex("#D32F2F"),
            on_release=self._confirm_clear_log,
        )
        btn_row.add_widget(btn_export)
        btn_row.add_widget(btn_clear)
        card.add_widget(btn_row)

        return card

    def _refresh_log(self):
        self._log_container.clear_widgets()
        logs = data_mgr.get_logs()[:20]  # 只显示最近 20 条
        if not logs:
            self._log_container.add_widget(make_label("暂无日志记录", font_size=dp(12)))
            return
        for r in logs:
            row = MDBoxLayout(size_hint_y=None, height=dp(40), spacing=dp(4))
            for val, w in [(r["ts"][:16], 0.38), (r["mc"], 0.15),
                           (r["name"][:8], 0.27), (r["pw"], 0.2)]:
                lbl = MDLabel(
                    text=val,
                    font_size=dp(11),
                    size_hint_x=w,
                    halign="center",
                    theme_text_color="Secondary",
                )
                lbl.bind(size=lbl.setter("text_size"))
                row.add_widget(lbl)
            self._log_container.add_widget(row)

    def _export_log(self, *_):
        path = data_mgr.export_txt()
        show_toast(f"已导出到: {path}", 3.0)

    def _confirm_clear_log(self, *_):
        dlg = MDDialog(
            title="确认清空",
            text="确定要清空所有授权日志吗？此操作不可恢复。",
            buttons=[
                MDFlatButton(text="取消", on_release=lambda x: dlg.dismiss()),
                MDRaisedButton(
                    text="确认清空",
                    md_bg_color=get_color_from_hex("#D32F2F"),
                    on_release=lambda x: self._do_clear_log(dlg),
                ),
            ],
        )
        dlg.open()

    def _do_clear_log(self, dlg):
        dlg.dismiss()
        data_mgr.clear_logs()
        self._refresh_log()
        show_toast("日志已清空")

    # ─ 系统设置卡片 ──────────────────────────────
    def _build_settings_card(self) -> MDCard:
        card = make_section_card()
        card.add_widget(make_label("系统设置", font_size=dp(15), bold=True))

        settings = data_mgr.load_settings()

        # 深色模式
        theme_row = MDBoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        theme_row.add_widget(make_label("深色模式"))
        self.sw_dark = MDSwitch(active=settings.get("theme", "Light") == "Dark")
        self.sw_dark.bind(active=self._on_theme_changed)
        theme_row.add_widget(self.sw_dark)
        card.add_widget(theme_row)

        # 自动复制
        copy_row = MDBoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        copy_row.add_widget(make_label("生成后自动复制密码"))
        self.sw_auto_copy = MDSwitch(active=settings.get("auto_copy", False))
        self.sw_auto_copy.bind(active=self._on_settings_changed)
        copy_row.add_widget(self.sw_auto_copy)
        card.add_widget(copy_row)

        # 关于
        card.add_widget(make_label("─" * 40, font_size=dp(10)))
        about = MDLabel(
            text=(
                "[b]PLC 集成商时间锁授权工具 安卓版 V1.0[/b]\n"
                "纯离线运行 | 算法与 PC 端 100% 一致\n"
                "适配安卓 8.0 及以上版本"
            ),
            markup=True,
            font_size=dp(12),
            size_hint_y=None,
            height=dp(64),
            theme_text_color="Secondary",
        )
        about.bind(size=about.setter("text_size"))
        card.add_widget(about)

        return card

    def _on_theme_changed(self, instance, value):
        app = MDApp.get_running_app()
        app.theme_cls.theme_style = "Dark" if value else "Light"
        self._save_settings()

    def _on_settings_changed(self, *_):
        self._save_settings()

    def _save_settings(self):
        s = data_mgr.load_settings()
        s["theme"] = "Dark" if self.sw_dark.active else "Light"
        s["auto_copy"] = self.sw_auto_copy.active
        data_mgr.save_settings(s)


# ═══════════════════════════════════════════════
#   主 App
# ═══════════════════════════════════════════════
class PLCTimeLockApp(MDApp):
    def build(self):
        self.title = "PLC 时间锁授权工具"
        self.theme_cls.primary_palette = "Blue"
        self.theme_cls.primary_hue = "700"

        # 初始化数据管理器
        data_mgr.init()

        # 加载设置
        settings = data_mgr.load_settings()
        self.theme_cls.theme_style = settings.get("theme", "Light")

        # 构建主布局
        main_layout = MDBoxLayout(orientation="vertical")

        # 顶部标题栏（自定义，避免中文乱码）
        self.top_bar = CustomTopBar()
        main_layout.add_widget(self.top_bar)

        # 底部导航
        bottom_nav = MDBottomNavigation(panel_color=get_color_from_hex("#1976D2"))

        # Tab1 — 密码生成
        tab1 = MDBottomNavigationItem(name="generator", text="密码生成", icon="key")
        self.gen_screen = GeneratorScreen(name="gen", top_bar=self.top_bar)
        tab1.add_widget(self.gen_screen)

        # Tab2 — 密码验证
        tab2 = MDBottomNavigationItem(name="verify", text="验证", icon="check-circle")
        self.verify_screen = VerifyScreen(name="verify", generator=self.gen_screen)
        tab2.add_widget(self.verify_screen)

        # Tab3 — 更多功能
        tab3 = MDBottomNavigationItem(name="more", text="更多", icon="dots-horizontal")
        self.more_screen = MoreScreen(name="more", generator=self.gen_screen)
        tab3.add_widget(self.more_screen)

        bottom_nav.add_widget(tab1)
        bottom_nav.add_widget(tab2)
        bottom_nav.add_widget(tab3)

        # 切换 Tab 时更新顶部标题
        bottom_nav.bind(current=self._on_tab_changed)

        main_layout.add_widget(bottom_nav)

        # 恢复上次的公式
        cf = data_mgr.load_current_formula()
        self.gen_screen.current_formula = cf["formula"]
        self.gen_screen.current_formula_name = cf["name"]
        self.gen_screen.current_mc_mode = cf.get("mc_mode", "hex")
        self.top_bar.set_subtitle(f"当前公式: {cf['name']}")

        return main_layout

    def _on_tab_changed(self, instance, value):
        titles = {
            "generator": "PLC 时间锁生成器",
            "verify": "密码验证",
            "more": "更多功能",
        }
        self.top_bar._title_lbl.text = titles.get(value, "PLC 时间锁生成器")
        if value != "generator":
            self.top_bar.set_subtitle("")
        else:
            self.top_bar.set_subtitle(
                f"当前公式: {self.gen_screen.current_formula_name}")

    def on_pause(self):
        return True

    def on_resume(self):
        pass


# ═══════════════════════════════════════════════
#   入口
# ═══════════════════════════════════════════════
if __name__ == "__main__":
    PLCTimeLockApp().run()
