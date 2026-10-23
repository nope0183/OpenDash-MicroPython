"""SHFW screens and touch handling, loaded only when the menu is opened.

Keeping this module out of the boot path saves roughly 16 KB of bytecode on
an ESP32 CYD without PSRAM.  The functions receive the UI instance as ``ui``.
"""
try:
    from . import colors as C
    from . import shfw
    from .display import Canvas
except ImportError:
    from opendash import colors as C
    from opendash import shfw
    from opendash.display import Canvas

# Keep in sync with ui.py.  Duplicating five integers avoids a circular import
# from this module back into the UI while it is loading this module on demand.
SCR_SHFW = 12
SCR_SHFW_LIST = 13
SCR_SHFW_EDIT = 14
SCR_SHFW_BAK = 15
SCR_SHFW_PROF = 16


def hit(x, y, rx, ry, rw, rh):
    return rx <= x < rx + rw and ry <= y < ry + rh


def shfw_fit(ui, text, font, maxw):
    if Canvas.text_width(text, font) <= maxw:
        return text
    text = text[:-1]
    while text:
        clipped = text + ".."
        if Canvas.text_width(clipped, font) <= maxw:
            return clipped
        text = text[:-1]
    return ""

def shfw_wrap(ui, text, x, y, w, lines, font=1, color=None):
    color = C.COL_TXT if color is None else color
    rest = text
    for i in range(lines):
        if not rest:
            return
        if i == lines - 1:
            line = shfw_fit(ui, rest, font, w)
            rest = ""
        else:
            cut = len(rest)
            while cut and Canvas.text_width(rest[:cut], font) > w:
                cut -= 1
            if cut <= 0:
                cut = 1
            space = rest.rfind(" ", 0, cut)
            if space > 0:
                cut = space
            line = rest[:cut]
            rest = rest[cut:].strip()
        ui.text_at(x, y + i * 11, w, 11, line, font, color,
                     C.COL_BG, "tl", 1, w)

def shfw_busy(ui, text):
    ui.d.fill_rect(0, 298, 240, 22, C.COL_BG)
    ui.text_at(4, 298, 232, 22, shfw_fit(ui, text, 1, 228),
                 1, C.COL_WARN, C.COL_BG, "tl", 1, 228)

def shfw_result(ui, code, restore=False):
    nb = ui.nb
    col = C.COL_BAD
    if code == shfw.SHFW_OK:
        col = C.COL_GOOD
        text = ui.t(
            "Restored and verified. Previous settings are in the UNDO slot."
            if restore else "Done and verified.",
            "Восстановлено и проверено. Прежние настройки - в слоте Отмена."
            if restore else "Выполнено и проверено.")
    elif code == shfw.SHFW_LOCKED:
        col = C.COL_WARN
        text = ui.t("Editing is OFF (SHFW menu: hold)",
                      "Правка выключена (меню SHFW)")
    elif code == shfw.SHFW_NO_LINK:
        text = ui.t("No link to the scooter", "Нет связи с самокатом")
    elif code == shfw.SHFW_MOVING:
        col = C.COL_WARN
        text = ui.t("Stop the scooter and wait for speed data",
                      "Остановите самокат и дождитесь данных скорости")
    elif code == shfw.SHFW_NOT_DETECTED:
        text = ui.t("SHFW not detected - nothing written",
                      "SHFW не найдена - запись не выполнена")
    elif code == shfw.SHFW_READ_FAIL:
        text = ui.t("Read failed - nothing written",
                      "Чтение не удалось - ничего не записано")
    elif code == shfw.SHFW_VERIFY_FAIL:
        text = ui.t("Could not verify the write",
                      "Запись не удалось проверить")
    elif code == shfw.SHFW_NO_VERSION:
        text = ui.t("Version request got no answer - nothing done",
                      "Версия не получена - ничего не сделано")
    elif code == shfw.SHFW_EMPTY:
        col = C.COL_WARN
        text = ui.t("Slot is empty", "Слот пуст")
    elif code == shfw.SHFW_BAD_SLOT:
        text = ui.t("Slot is damaged or from another table",
                      "Слот повреждён или от другой таблицы")
    elif code == shfw.SHFW_VER_MISMATCH:
        text = ui.t("Version differs: saved %s / now %s",
                      "Версия другая: в копии %s / сейчас %s") % (
                          nb.shfw_hex(nb.shfw_saved_ver, 6),
                          nb.shfw_hex(nb.shfw_ver, 6))
    elif code == shfw.SHFW_SAVE_FAIL:
        text = ui.t("Could not save to flash", "Не удалось сохранить во flash")
    elif code == shfw.SHFW_WRITE_FAIL:
        text = ui.t(
            "Restore incomplete: %d block(s) not applied, first at reg 0x%02X. UNDO has the previous state.",
            "Восстановление неполное: %d блок(ов) не принято, первый с рег. 0x%02X. Прежнее - в слоте Отмена."
        ) % (nb.shfw_last_fail_count, nb.shfw_last_fail_reg)
    elif code == shfw.SHFW_RESERVED:
        col = C.COL_WARN
        text = ui.t("UNDO slot is filled automatically",
                      "Слот Отмена заполняется автоматически")
    elif code == shfw.SHFW_NOCHANGE:
        col = C.COL_GOOD
        text = ui.t("Already matches the backup - nothing written",
                      "Уже совпадает с копией - ничего не записано")
    else:
        text = "SHFW error %d" % code
    ui.shfw_msg = text
    ui.shfw_msg_col = col

def open_shfw(ui):
    ui.shfw_msg = ""
    ui.nb.shfw_reset(lock=False)
    ui.enter(SCR_SHFW)
    if ui.nb.is_live():
        ui.draw_settings()
        shfw_busy(ui, ui.t("Checking SHFW...", "Проверка SHFW..."))
        ui.nb.shfw_detect()
    ui.settings_dirty = True

def shfw_open_group(ui, group):
    ui.shfw_grp = group
    ui.shfw_page = 0
    ui.shfw_list = shfw.GROUP_ITEMS[group]
    ui.shfw_sel = -1
    ui.enter(SCR_SHFW_LIST)
    ui.draw_settings()
    shfw_load_page(ui)

def shfw_load_page(ui):
    first = ui.shfw_page * 6
    page = ui.shfw_list[first:first + 6]
    shfw_busy(ui, ui.t("Reading from scooter...", "Чтение из самоката..."))
    ui.nb.shfw_prefetch(page)
    ui.settings_dirty = True

def shfw_change_page(ui, delta):
    pages = (len(ui.shfw_list) + 5) // 6
    if pages <= 1:
        return
    ui.shfw_page = (ui.shfw_page + delta + pages) % pages
    shfw_load_page(ui)

def shfw_open_item(ui, index):
    ui.shfw_sel = index
    ui.shfw_msg = ""
    ui.shfw_edit_ready = False
    ui.enter(SCR_SHFW_EDIT)
    ui.draw_settings()
    shfw_busy(ui, ui.t("Reading from scooter...", "Чтение из самоката..."))
    item = shfw.ITEMS[index]
    word = ui.nb.shfw_read_reg(item[1], item[2])
    if word is None:
        shfw_result(ui, shfw.SHFW_READ_FAIL)
    else:
        ui.shfw_orig = ui.shfw_edit = shfw.field(item, word)
        ui.shfw_edit_ready = True
    ui.settings_dirty = True

def shfw_do_apply(ui):
    if ui.shfw_sel < 0 or not ui.shfw_edit_ready:
        return
    if ui.shfw_edit == ui.shfw_orig:
        return
    item = shfw.ITEMS[ui.shfw_sel]
    shfw_busy(ui, ui.t("Writing...", "Запись..."))
    code = ui.nb.shfw_write_item(item, ui.shfw_edit)
    if code == shfw.SHFW_OK:
        value = ui.nb.shfw_cached(item)
        if value is None:
            ui.shfw_orig = ui.shfw_edit
        else:
            ui.shfw_orig = ui.shfw_edit = value
        ui.shfw_msg = ui.t("Written and verified", "Записано и проверено")
        ui.shfw_msg_col = C.COL_GOOD
    elif code == shfw.SHFW_VERIFY_FAIL:
        value = ui.nb.shfw_cached(item)
        if value is None:
            shfw_result(ui, code)
        else:
            ui.shfw_orig = value
            ui.shfw_msg = ui.t(
                "Not applied, reads back: %s",
                "Не принято, читается: %s") % shfw.format_value(
                    item, value, ui.cfg["lang"])
            ui.shfw_msg_col = C.COL_BAD
    else:
        shfw_result(ui, code)
    ui.settings_dirty = True

def shfw_open_backup(ui):
    ui.shfw_msg = ""
    ui.shfw_bak_sel = 0
    ui.enter(SCR_SHFW_BAK)
    if ui.nb.is_live():
        ui.draw_settings()
        shfw_busy(ui, ui.t("Reading version...", "Чтение версии..."))
        ui.nb.shfw_read_version()
    ui.shfw_bak_slots = ui.nb.shfw_dump_slots()
    ui.settings_dirty = True

def shfw_do_backup(ui):
    shfw_busy(ui, ui.t("Reading config...", "Чтение настроек..."))
    code = ui.nb.shfw_backup(ui.shfw_bak_sel)
    ui.shfw_bak_slots = ui.nb.shfw_dump_slots()
    if code == shfw.SHFW_OK:
        ui.shfw_msg = "%s %d" % (
            ui.t("Saved to slot", "Сохранено в слот"), ui.shfw_bak_sel + 1)
        ui.shfw_msg_col = C.COL_GOOD
    else:
        shfw_result(ui, code)
    ui.settings_dirty = True

def shfw_do_restore(ui):
    shfw_busy(ui, ui.t("Restoring...", "Восстановление..."))
    code = ui.nb.shfw_restore(ui.shfw_bak_sel)
    ui.shfw_bak_slots = ui.nb.shfw_dump_slots()
    shfw_result(ui, code, True)
    ui.settings_dirty = True

def shfw_open_profiles(ui):
    ui.shfw_msg = ""
    ui.shfw_prof_active = 0
    ui.enter(SCR_SHFW_PROF)
    if ui.nb.is_live():
        ui.draw_settings()
        shfw_busy(ui, ui.t("Reading profile...", "Чтение профиля..."))
        ui.nb.shfw_read_version()
        ui.shfw_prof_active = ui.nb.shfw_active_profile()
    ui.shfw_prof_sel = (ui.shfw_prof_active - 1
                          if ui.shfw_prof_active else 0)
    ui.shfw_prof_slots = ui.nb.shfw_profile_slots()
    ui.settings_dirty = True

def shfw_do_profile_switch(ui):
    if ui.shfw_prof_sel > 2:
        ui.shfw_msg = ui.t("Select profile 1-3", "Выберите профиль 1-3")
        ui.shfw_msg_col = C.COL_WARN
        ui.settings_dirty = True
        return
    profile = ui.shfw_prof_sel + 1
    shfw_busy(ui, ui.t("Switching profile...", "Переключение профиля..."))
    code = ui.nb.shfw_profile_switch(profile)
    if code == shfw.SHFW_OK:
        ui.shfw_prof_active = profile
        ui.shfw_msg = "%s %d" % (
            ui.t("Active profile:", "Активный профиль:"), profile)
        ui.shfw_msg_col = C.COL_GOOD
    else:
        shfw_result(ui, code)
    ui.settings_dirty = True

def shfw_do_profile_backup(ui):
    if ui.shfw_prof_sel > 2:
        ui.shfw_msg = ui.t("UNDO slot is filled automatically",
                               "Слот Отмена заполняется автоматически")
        ui.shfw_msg_col = C.COL_WARN
        ui.settings_dirty = True
        return
    shfw_busy(ui, ui.t("Reading profile...", "Чтение профиля..."))
    code = ui.nb.shfw_profile_backup(ui.shfw_prof_sel)
    ui.shfw_prof_slots = ui.nb.shfw_profile_slots()
    if code == shfw.SHFW_OK:
        if ui.nb.shfw_profile_got < shfw.PROFILE_WORDS:
            ui.shfw_msg = "%s %d/%d" % (
                ui.t("Saved, words read:", "Сохранено, прочитано слов:"),
                ui.nb.shfw_profile_got, shfw.PROFILE_WORDS)
            ui.shfw_msg_col = C.COL_WARN
        else:
            ui.shfw_msg = "%s %d" % (
                ui.t("Saved profile", "Сохранён профиль"),
                ui.shfw_prof_sel + 1)
            ui.shfw_msg_col = C.COL_GOOD
    else:
        shfw_result(ui, code)
    ui.settings_dirty = True

def shfw_do_profile_restore(ui):
    shfw_busy(ui, ui.t("Restoring profile...", "Восстановление профиля..."))
    code = ui.nb.shfw_profile_restore(ui.shfw_prof_sel)
    ui.shfw_prof_slots = ui.nb.shfw_profile_slots()
    if code == shfw.SHFW_OK:
        shfw_result(ui, code, True)
        ui.shfw_msg = ui.t(
            "Profile restored and verified. Previous state is in the UNDO slot.",
            "Профиль восстановлен и проверен. Прежний - в слоте Отмена.")
        ui.shfw_msg_col = C.COL_GOOD
    elif code == shfw.SHFW_NOCHANGE:
        shfw_result(ui, code)
    else:
        shfw_result(ui, code)
    ui.settings_dirty = True

def draw_set_shfw(ui):
    nb = ui.nb
    ui.settings_header(ui.t("SHFW SETTINGS", "Настройки SHFW"))
    if not nb.is_live():
        status = ui.t("Not connected to the scooter", "Нет связи с самокатом")
        col = C.COL_WARN
    elif nb.shfw_detected == 1:
        if nb.shfw_profile:
            status = ui.t("SHFW detected, active profile %d",
                            "SHFW найдена, активный профиль %d") % nb.shfw_profile
        else:
            status = ui.t("SHFW detected (version answered)",
                            "SHFW найдена (версия получена)")
        col = C.COL_GOOD
    elif nb.shfw_forced:
        status = ui.t("FORCED: SHFW not verified!",
                        "ПРИНУДИТЕЛЬНО: SHFW не проверена!")
        col = C.COL_WARN
    elif nb.shfw_detected < 0:
        status = ui.t("Reopen this menu to check SHFW",
                        "Откройте меню заново для проверки")
        col = C.COL_WARN
    else:
        status = ui.t("Not detected. HOLD here = force",
                        "Не найдена. Удерж. здесь = принуд.")
        col = C.COL_BAD
    ui.text_at(8, 32, 224, 16, shfw_fit(ui, status, 1, 224), 1,
                 col, C.COL_BG, "tl", 1, 224)

    fill = C.COL_WARN if nb.shfw_enabled else C.COL_PANEL
    fg = C.COL_BG if nb.shfw_enabled else C.COL_TXT
    dim = C.COL_BG if nb.shfw_enabled else C.COL_DIM
    ui.d.fill_round_rect(8, 50, 224, 40, 6, fill)
    ui.text_at(20, 52, 204, 20,
                 ui.t("EDITING: ON", "Правка: ВКЛ") if nb.shfw_enabled
                 else ui.t("EDITING: OFF", "Правка: ВЫКЛ"),
                 2, fg, fill, "tl", 1, 204)
    ui.text_at(20, 75, 204, 12,
                 ui.t("hold to change (resets on restart)",
                        "удерживайте (сбросится при перезапуске)"),
                 1, dim, fill, "tl", 1, 204)

    for g in range(6):
        y = 98 + g * 25
        ui.d.fill_round_rect(8, y, 224, 22, 6, C.COL_PANEL)
        ui.d.fill_rect(8, y + 3, 3, 16,
                         C.COL_BAD if g == 5 else C.COL_ACCENT)
        name = (shfw.GROUPS_RU if ui.cfg["lang"] else shfw.GROUPS_EN)[g]
        ui.text_at(20, y, 170, 22, shfw_fit(ui, name, 2, 170),
                     2, C.COL_BAD if g == 5 else C.COL_TXT,
                     C.COL_PANEL, "ml", 1, 170)
        ui.text_at(194, y, 20, 22, "%d" % shfw.GROUP_COUNTS[g],
                     2, C.COL_DIM, C.COL_PANEL, "mr", 1, 20)
        ui.d.line(216, y + 6, 222, y + 11, C.COL_DIM)
        ui.d.line(222, y + 11, 216, y + 16, C.COL_DIM)

    y = 98 + 6 * 25
    ui.d.fill_round_rect(8, y, 224, 22, 6, C.COL_PANEL)
    ui.d.fill_rect(8, y + 3, 3, 16, C.COL_GOOD)
    ui.text_at(20, y, 180, 22, ui.t("Profiles", "Профили"),
                 2, C.COL_TXT, C.COL_PANEL, "ml", 1, 180)
    ui.d.line(216, y + 6, 222, y + 11, C.COL_DIM)
    ui.d.line(222, y + 11, 216, y + 16, C.COL_DIM)

    y += 25
    ui.d.fill_round_rect(8, y, 224, 22, 6, C.COL_PANEL)
    ui.d.fill_rect(8, y + 3, 3, 16, C.COL_WARN)
    ui.text_at(20, y, 180, 22, ui.t("Backup / restore",
                                        "Копии / восстановление"),
                 2, C.COL_TXT, C.COL_PANEL, "ml", 1, 180)
    ui.d.line(216, y + 6, 222, y + 11, C.COL_DIM)
    ui.d.line(222, y + 11, 216, y + 16, C.COL_DIM)

    ui.text_at(8, 296, 224, 12,
                 ui.t("Standstill only; verified after write",
                        "Только на стоянке; запись проверяется"),
                 1, C.COL_DIM, C.COL_BG, "tl", 1, 224)
    diag = (nb.shfw_diag if nb.is_live() and nb.shfw_detected >= 0 and nb.shfw_diag
            else ui.t("Wrong values can damage the scooter",
                        "Неверные значения могут повредить"))
    ui.text_at(8, 307, 224, 12, shfw_fit(ui, diag, 1, 224), 1,
                 C.COL_DIM, C.COL_BG, "tl", 1, 224)

def draw_shfw_list(ui):
    if shfw is None:
        ui.draw_set_shfw()
        return
    name = (shfw.GROUPS_RU if ui.cfg["lang"] else shfw.GROUPS_EN)[ui.shfw_grp]
    ui.settings_header(name)
    first = ui.shfw_page * 6
    for row in range(6):
        pos = first + row
        if pos >= len(ui.shfw_list):
            break
        item = shfw.ITEMS[ui.shfw_list[pos]]
        y = 34 + row * 40
        ui.d.fill_round_rect(8, y, 224, 38, 6, C.COL_PANEL)
        ui.d.fill_rect(8, y + 5, 3, 28,
                         C.COL_BAD if item[3] == 5 else C.COL_ACCENT)
        ui.text_at(18, y + 2, 190, 12,
                     shfw_fit(ui, item[0], 1, 190), 1,
                     C.COL_DIM, C.COL_PANEL, "tl", 1, 190)
        value = ui.nb.shfw_cached(item)
        if value is None:
            text = "--"
        else:
            text = shfw.format_value(item, value, ui.cfg["lang"])
        ui.text_at(18, y + 14, 190, 22,
                     shfw_fit(ui, text, 2, 190), 2,
                     C.COL_TXT, C.COL_PANEL, "tl", 1, 190)
        ui.d.line(216, y + 13, 222, y + 19, C.COL_DIM)
        ui.d.line(222, y + 19, 216, y + 25, C.COL_DIM)
    pages = (len(ui.shfw_list) + 5) // 6
    ui.btn(8, 282, 64, 32, "<", False, 2)
    ui.btn(168, 282, 64, 32, ">", False, 2)
    ui.btn(80, 282, 80, 32, "%d / %d" % (ui.shfw_page + 1, pages),
             False, 2)

def draw_shfw_edit(ui):
    if shfw is None:
        ui.draw_set_shfw()
        return
    if ui.shfw_sel < 0:
        return
    item = shfw.ITEMS[ui.shfw_sel]
    name = (shfw.GROUPS_RU if ui.cfg["lang"] else shfw.GROUPS_EN)[item[3]]
    ui.settings_header(name)
    shfw_wrap(ui, item[0], 8, 34, 224, 2, 1, C.COL_TXT)
    if ui.shfw_edit_ready:
        value = shfw.format_value(item, ui.shfw_edit, ui.cfg["lang"])
    else:
        value = "--"
    vfont = 2 if item[4] == shfw.KIND_ENUM else 4
    if Canvas.text_width(value, vfont) > 224:
        vfont = 2
    col = (C.COL_ACCENT if ui.shfw_edit_ready
           and ui.shfw_edit != ui.shfw_orig else C.COL_TXT)
    ui.text_at(8, 58, 224, 34, value, vfont, col, C.COL_BG,
                 "mc", 1, 224)
    if ui.shfw_edit_ready:
        now = shfw.format_value(item, ui.shfw_orig, ui.cfg["lang"])
        ui.text_at(8, 96, 224, 12, "%s %s" % (
            ui.t("now:", "сейчас:"), shfw_fit(ui, now, 1, 180)),
            1, C.COL_DIM, C.COL_BG, "tc", 1, 224)
    if item[4] == shfw.KIND_NUM:
        lo = shfw.format_value(item, item[6], ui.cfg["lang"])
        hi = shfw.format_value(item, item[7], ui.cfg["lang"])
        ui.text_at(8, 108, 224, 12, "%s %s .. %s" % (
            ui.t("range:", "диапазон:"), lo, hi),
            1, C.COL_DIM, C.COL_BG, "tc", 1, 224)
        s1, s2 = shfw.steps(item)
        ui.btn(8, 124, 52, 44, "-%d" % s2, False, 2)
        ui.btn(64, 124, 52, 44, "-%d" % s1, False, 2)
        ui.btn(120, 124, 52, 44, "+%d" % s1, False, 2)
        ui.btn(176, 124, 52, 44, "+%d" % s2, False, 2)
    elif item[4] == shfw.KIND_ENUM:
        ui.btn(8, 124, 108, 44, "<", False, 4)
        ui.btn(124, 124, 108, 44, ">", False, 4)
    else:
        ui.btn(8, 124, 108, 44, ui.t("OFF", "ВЫКЛ"),
                 ui.shfw_edit_ready and ui.shfw_edit == 0)
        ui.btn(124, 124, 108, 44, ui.t("ON", "ВКЛ"),
                 ui.shfw_edit_ready and ui.shfw_edit == 1)

    ui.btn(8, 176, 100, 44, ui.t("REVERT", "Отмена"), False, 2)
    can_write = (ui.nb.shfw_enabled and ui.nb.shfw_detected == 1
                 and ui.shfw_edit_ready and ui.shfw_edit != ui.shfw_orig)
    fill = (C.COL_BAD if item[3] == 5 else C.COL_ACCENT) if can_write else C.COL_PANEL
    ui.d.fill_round_rect(116, 176, 116, 44, 6, fill)
    fg = C.COL_BG if can_write else C.COL_DIM
    ui.text_at(120, 180, 108, 22, ui.t("WRITE", "ЗАПИСЬ"),
                 2, fg, fill, "mc", 1, 108)
    ui.text_at(120, 201, 108, 12,
                 ui.t("hold to confirm", "удерживайте"),
                 1, fg, fill, "mc", 1, 108)
    if ui.shfw_msg:
        shfw_wrap(ui, ui.shfw_msg, 8, 228, 224, 3, 1,
                       ui.shfw_msg_col)
    if not ui.nb.shfw_enabled:
        warn = ui.t("Editing is OFF (SHFW menu: hold)",
                      "Правка выключена (меню SHFW)")
        wcol = C.COL_WARN
    elif item[3] == 5:
        warn = ui.t("EXPERT: wrong values can damage it",
                      "ЭКСПЕРТ: можно повредить самокат")
        wcol = C.COL_BAD
    else:
        warn = ""
        wcol = C.COL_WARN
    if warn:
        ui.text_at(8, 300, 224, 12, shfw_fit(ui, warn, 1, 224),
                     1, wcol, C.COL_BG, "tl", 1, 224)

def draw_shfw_backup(ui):
    ui.settings_header(ui.t("SHFW BACKUP", "Копии SHFW"))
    nb = ui.nb
    if nb.shfw_ver:
        ver = ui.t("version:", "версия:") + " " + nb.shfw_hex(nb.shfw_ver, 14)
    else:
        ver = ui.t("version: unknown", "версия: неизвестна")
    ui.text_at(8, 32, 224, 12, shfw_fit(ui, ver, 1, 224),
                 1, C.COL_DIM, C.COL_BG, "tl", 1, 224)
    for i in range(3):
        y = 48 + i * 36
        state, slot_ver = (ui.shfw_bak_slots[i]
                           if i < len(ui.shfw_bak_slots) else (0, b""))
        ui.d.fill_round_rect(8, y, 224, 33, 6, C.COL_PANEL)
        if i == ui.shfw_bak_sel:
            ui.d.rect(8, y, 224, 33, C.COL_ACCENT)
        ui.text_at(16, y + 1, 160, 20,
                     "%s %d" % (ui.t("Slot", "Слот"), i + 1),
                     2, C.COL_TXT, C.COL_PANEL, "tl", 1, 160)
        if state == 1:
            ui.text_at(16, y + 20, 120, 12,
                         nb.shfw_hex(slot_ver, 8), 1,
                         C.COL_DIM, C.COL_PANEL, "tl", 1, 120)
            same = bool(nb.shfw_ver) and slot_ver == nb.shfw_ver
            ui.text_at(140, y + 20, 84, 12,
                         ui.t("version OK", "версия совпадает") if same
                         else ui.t("other version", "другая версия"),
                         1, C.COL_GOOD if same else C.COL_BAD,
                         C.COL_PANEL, "tr", 1, 84)
        else:
            label = (ui.t("damaged", "повреждён") if state < 0
                     else ui.t("empty", "пусто"))
            ui.text_at(16, y + 20, 180, 12, label, 1,
                         C.COL_BAD if state < 0 else C.COL_DIM,
                         C.COL_PANEL, "tl", 1, 180)
    ui.d.fill_round_rect(8, 234, 108, 40, 6, C.COL_PANEL)
    ui.text_at(12, 237, 100, 18, ui.t("BACKUP", "КОПИЯ"),
                 2, C.COL_TXT, C.COL_PANEL, "mc", 1, 100)
    ui.text_at(12, 256, 100, 12,
                 ui.t("hold = overwrite", "удерж.=замена"),
                 1, C.COL_DIM, C.COL_PANEL, "mc", 1, 100)
    fill = C.COL_ACCENT if nb.shfw_enabled else C.COL_PANEL
    fg = C.COL_BG if nb.shfw_enabled else C.COL_DIM
    ui.d.fill_round_rect(124, 234, 108, 40, 6, fill)
    ui.text_at(128, 237, 100, 18,
                 ui.t("RESTORE", "ВОССТАНОВИТЬ"),
                 2, fg, fill, "mc", 1, 100)
    ui.text_at(128, 256, 100, 12,
                 ui.t("hold", "удерживайте") if nb.shfw_enabled
                 else ui.t("editing is OFF", "правка выключена"),
                 1, fg, fill, "mc", 1, 100)
    if ui.shfw_msg:
        shfw_wrap(ui, ui.shfw_msg, 8, 278, 224, 3, 1,
                       ui.shfw_msg_col)

def draw_shfw_profiles(ui):
    ui.settings_header(ui.t("SHFW PROFILES", "Профили SHFW"))
    nb = ui.nb
    if ui.shfw_prof_active:
        text = "%s %d" % (ui.t("active profile:", "активный профиль:"),
                          ui.shfw_prof_active)
    else:
        text = ui.t("active profile: unknown",
                      "активный профиль: неизвестен")
    ui.text_at(8, 32, 224, 12, shfw_fit(ui, text, 1, 224),
                 1, C.COL_DIM, C.COL_BG, "tl", 1, 224)
    for i in range(4):
        y = 48 + i * 36
        if i < len(ui.shfw_prof_slots):
            state, profile, slot_ver = ui.shfw_prof_slots[i]
        else:
            state, profile, slot_ver = 0, 0, b""
        ui.d.fill_round_rect(8, y, 224, 33, 6, C.COL_PANEL)
        if i == ui.shfw_prof_sel:
            ui.d.rect(8, y, 224, 33, C.COL_ACCENT)
        if i < 3:
            label = "%s %d" % (ui.t("Profile", "Профиль"), i + 1)
        elif state == 1:
            label = "%s %d)" % (ui.t("UNDO (auto, profile",
                                       "Отмена (авто, профиль"), profile)
        else:
            label = ui.t("UNDO (auto, before restore)",
                           "Отмена (авто, до восстановления)")
        ui.text_at(16, y + 1, 165, 20, shfw_fit(ui, label, 2, 165),
                     2, C.COL_TXT, C.COL_PANEL, "tl", 1, 165)
        if i < 3 and ui.shfw_prof_active == i + 1:
            ui.text_at(182, y + 4, 42, 12,
                         ui.t("ACTIVE", "АКТИВЕН"), 1,
                         C.COL_GOOD, C.COL_PANEL, "tr", 1, 42)
        if state == 1:
            ui.text_at(16, y + 20, 120, 12,
                         nb.shfw_hex(slot_ver, 8), 1,
                         C.COL_DIM, C.COL_PANEL, "tl", 1, 120)
            same = bool(nb.shfw_ver) and slot_ver == nb.shfw_ver
            ui.text_at(140, y + 20, 84, 12,
                         ui.t("version OK", "версия совпадает") if same
                         else ui.t("other version", "другая версия"),
                         1, C.COL_GOOD if same else C.COL_BAD,
                         C.COL_PANEL, "tr", 1, 84)
        else:
            label = (ui.t("damaged", "повреждён") if state < 0
                     else ui.t("no backup", "нет копии"))
            ui.text_at(16, y + 20, 180, 12, label, 1,
                         C.COL_BAD if state < 0 else C.COL_DIM,
                         C.COL_PANEL, "tl", 1, 180)

    fill = C.COL_ACCENT if nb.shfw_enabled else C.COL_PANEL
    fg = C.COL_BG if nb.shfw_enabled else C.COL_DIM
    ui.d.fill_round_rect(8, 194, 108, 40, 6, fill)
    ui.text_at(12, 197, 100, 18, ui.t("SWITCH", "ВКЛЮЧИТЬ"),
                 2, fg, fill, "mc", 1, 100)
    ui.text_at(12, 216, 100, 12,
                 ui.t("hold", "удерживайте") if nb.shfw_enabled
                 else ui.t("editing is OFF", "правка выключена"),
                 1, fg, fill, "mc", 1, 100)
    ui.d.fill_round_rect(124, 194, 108, 40, 6, C.COL_PANEL)
    ui.text_at(128, 197, 100, 18, ui.t("BACKUP", "КОПИЯ"),
                 2, C.COL_TXT, C.COL_PANEL, "mc", 1, 100)
    ui.text_at(128, 216, 100, 12,
                 ui.t("hold = overwrite", "удерж.=замена"),
                 1, C.COL_DIM, C.COL_PANEL, "mc", 1, 100)
    ui.d.fill_round_rect(8, 238, 224, 34, 6, fill)
    ui.text_at(12, 241, 216, 18,
                 ui.t("RESTORE", "ВОССТАНОВИТЬ"),
                 2, fg, fill, "mc", 1, 216)
    ui.text_at(12, 258, 216, 12,
                 ui.t("hold", "удерживайте") if nb.shfw_enabled
                 else ui.t("editing is OFF", "правка выключена"),
                 1, fg, fill, "mc", 1, 216)
    if ui.shfw_msg:
        shfw_wrap(ui, ui.shfw_msg, 8, 278, 224, 3, 1,
                       ui.shfw_msg_col)

def touch_shfw(ui, t, x, y):
    if shfw is None:
        return
    scr = ui.scr
    nb = ui.nb
    if scr == SCR_SHFW:
        if (t.ev_long and hit(x, y, 8, 32, 224, 16) and nb.is_live()
                and nb.shfw_detected >= 0
                and (nb.shfw_detected == 0 or nb.shfw_forced)):
            nb.shfw_force = not nb.shfw_force
            shfw_busy(ui, ui.t("Checking SHFW...", "Проверка SHFW..."))
            nb.shfw_detect()
            ui.settings_dirty = True
            return
        if t.ev_long and hit(x, y, 8, 50, 224, 40):
            nb.shfw_enabled = not nb.shfw_enabled
            ui.settings_dirty = True
            return
        if not t.ev_tap:
            return
        for g in range(6):
            if hit(x, y, 8, 98 + g * 25, 224, 22):
                shfw_open_group(ui, g)
                return
        if hit(x, y, 8, 98 + 6 * 25, 224, 22):
            shfw_open_profiles(ui)
            return
        if hit(x, y, 8, 98 + 7 * 25, 224, 22):
            shfw_open_backup(ui)
        return

    if scr == SCR_SHFW_LIST:
        if not t.ev_tap:
            return
        first = ui.shfw_page * 6
        for row in range(6):
            pos = first + row
            if pos < len(ui.shfw_list) and hit(x, y, 8, 34 + row * 40,
                                                 224, 38):
                shfw_open_item(ui, ui.shfw_list[pos])
                return
        pages = (len(ui.shfw_list) + 5) // 6
        if pages > 1 and hit(x, y, 8, 282, 64, 32):
            shfw_change_page(ui, -1)
        elif pages > 1 and hit(x, y, 168, 282, 64, 32):
            shfw_change_page(ui, 1)
        return

    if scr == SCR_SHFW_EDIT:
        if ui.shfw_sel < 0:
            return
        item = shfw.ITEMS[ui.shfw_sel]
        if t.ev_long and hit(x, y, 116, 176, 116, 44):
            shfw_do_apply(ui)
            return
        if not t.ev_tap:
            return
        if ui.shfw_edit_ready:
            value = ui.shfw_edit
            changed = True
            if item[4] == shfw.KIND_NUM:
                s1, s2 = shfw.steps(item)
                if hit(x, y, 8, 124, 52, 44):
                    value -= s2
                elif hit(x, y, 64, 124, 52, 44):
                    value -= s1
                elif hit(x, y, 120, 124, 52, 44):
                    value += s1
                elif hit(x, y, 176, 124, 52, 44):
                    value += s2
                else:
                    changed = False
            elif item[4] == shfw.KIND_ENUM:
                if hit(x, y, 8, 124, 108, 44):
                    value = shfw.enum_step(item, value, -1)
                elif hit(x, y, 124, 124, 108, 44):
                    value = shfw.enum_step(item, value, 1)
                else:
                    changed = False
            else:
                if hit(x, y, 8, 124, 108, 44):
                    value = 0
                elif hit(x, y, 124, 124, 108, 44):
                    value = 1
                else:
                    changed = False
            if changed:
                ui.shfw_edit = shfw.clamp(item, value)
                ui.shfw_msg = ""
                ui.settings_dirty = True
                return
        if hit(x, y, 8, 176, 100, 44):
            ui.shfw_edit = ui.shfw_orig
            ui.shfw_msg = ""
            ui.settings_dirty = True
        elif hit(x, y, 116, 176, 116, 44):
            ui.shfw_msg = ui.t("Hold the WRITE button to confirm",
                                   "Удерживайте кнопку ЗАПИСЬ")
            ui.shfw_msg_col = C.COL_WARN
            ui.settings_dirty = True
        return

    if scr == SCR_SHFW_BAK:
        if t.ev_long and hit(x, y, 8, 234, 108, 40):
            shfw_do_backup(ui)
            return
        if t.ev_long and hit(x, y, 124, 234, 108, 40):
            shfw_do_restore(ui)
            return
        if not t.ev_tap:
            return
        for i in range(3):
            if hit(x, y, 8, 48 + i * 36, 224, 33):
                ui.shfw_bak_sel = i
                ui.shfw_msg = ""
                ui.settings_dirty = True
                return
        if hit(x, y, 8, 234, 108, 40):
            state = (ui.shfw_bak_slots[ui.shfw_bak_sel][0]
                     if ui.shfw_bak_sel < len(ui.shfw_bak_slots) else 0)
            if state == 0:
                shfw_do_backup(ui)
            else:
                ui.shfw_msg = ui.t("Hold BACKUP to overwrite the slot",
                                       "Удерживайте КОПИЯ для замены слота")
                ui.shfw_msg_col = C.COL_WARN
                ui.settings_dirty = True
        elif hit(x, y, 124, 234, 108, 40):
            ui.shfw_msg = ui.t("Hold RESTORE to confirm",
                                   "Удерживайте ВОССТАНОВИТЬ")
            ui.shfw_msg_col = C.COL_WARN
            ui.settings_dirty = True
        return

    if scr == SCR_SHFW_PROF:
        if t.ev_long and hit(x, y, 8, 194, 108, 40):
            shfw_do_profile_switch(ui)
            return
        if t.ev_long and hit(x, y, 124, 194, 108, 40):
            shfw_do_profile_backup(ui)
            return
        if t.ev_long and hit(x, y, 8, 238, 224, 34):
            shfw_do_profile_restore(ui)
            return
        if not t.ev_tap:
            return
        for i in range(4):
            if hit(x, y, 8, 48 + i * 36, 224, 33):
                ui.shfw_prof_sel = i
                ui.shfw_msg = ""
                ui.settings_dirty = True
                return
        if hit(x, y, 8, 194, 108, 40):
            ui.shfw_msg = ui.t(
                "Hold SWITCH to change the active profile",
                "Удерживайте ВКЛЮЧИТЬ для смены профиля")
            ui.shfw_msg_col = C.COL_WARN
            ui.settings_dirty = True
        elif hit(x, y, 124, 194, 108, 40):
            state = (ui.shfw_prof_slots[ui.shfw_prof_sel][0]
                     if ui.shfw_prof_sel < len(ui.shfw_prof_slots) else 0)
            if ui.shfw_prof_sel < 3 and state == 0:
                shfw_do_profile_backup(ui)
            else:
                ui.shfw_msg = ui.t(
                    "Hold BACKUP to overwrite the backup",
                    "Удерживайте КОПИЯ для замены копии")
                ui.shfw_msg_col = C.COL_WARN
                ui.settings_dirty = True
        elif hit(x, y, 8, 238, 224, 34):
            ui.shfw_msg = ui.t("Hold RESTORE to confirm",
                                   "Удерживайте ВОССТАНОВИТЬ")
            ui.shfw_msg_col = C.COL_WARN
            ui.settings_dirty = True

# ---------------------------------------------------------- calibration
