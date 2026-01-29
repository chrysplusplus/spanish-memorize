from tui import (
         AcceleratorMap, CheckboxMenu, Layout, MenuScreen, ScreenBase, TUI_BEGIN_STATE,
         TUI_END_STATE, TUI_KEY_BACKSPACE, TUI_KEY_DOWN, TUI_KEY_ENTER, TUI_KEY_EVENT,
         TUI_KEY_UP, TUI_OK_EVENT, TuiContext, TuiKey, TuiProgram, as_ctrl_key, as_key,
         key_to_str, on_quit)
from data import (
        Category, Class, LanguagesKey, MINIMUM_STREAK_DISPLAY, PracticeSession,
        comiseration, congratulation, get_random_word, make_language_dictionary)

import curses

SELECT_LANG_STATE = TUI_BEGIN_STATE + 1
MAKE_SESSION_STATE = SELECT_LANG_STATE + 1
SELECT_ROUNDS_STATE = SELECT_LANG_STATE + 1
PLAY_MEMORIZE_STATE = SELECT_ROUNDS_STATE + 1
SELECT_MORE_ROUNDS_STATE = PLAY_MEMORIZE_STATE + 1
SUMMARY_STATE = SELECT_MORE_ROUNDS_STATE + 1

class CategorySelectionScreen(ScreenBase):
    '''Form for selecting cateogries from classes'''

    def __init__(self, prog_data: dict):
        self.prog_data = prog_data
        self.classes: list[Class] = prog_data['classes']
        self.title_str = "The following classes are available:"
        self.menus: list[CheckboxMenu] = []

        for index, class_ in enumerate(self.classes):
            class_id = index + 1
            menu = CheckboxMenu(title=f"{class_id}. {class_.name}")
            self.menus.append(menu)
            for cat_index, category in enumerate(class_.categories):
                cat_id = cat_index + 1
                menu.add_entry(f"{class_id}.{cat_id} {category.name}", enabled=True)

        self.cur_menu_idx = 0
        self.cur_entry_idx = 0

    def draw(self, tui: TuiContext):
        '''Form draw calls'''
        tui.clear_screen()
        tui.begin_draw()
        self.layout = Layout(centered_x=True, centered_y=True, padding=1, min_width=50)
        self.layout.add_to_tui(tui)
        self.layout.add_text(self.title_str)

        for menu in self.menus:
            menu.add_to_layout(self.layout)

        tui.end_draw()
        tui.refresh_screen()

        start_x, start_y = self.menus[0].entries[0].rendered_cursor_pos
        tui.move_cursor(start_x, start_y)

    def create_bindings(self, tui: TuiContext) -> None:
        '''Create form bindings'''
        self.accel_map = AcceleratorMap()
        self.accel_map.add_to_tui(tui)
        self.accel_map.map_key(TUI_KEY_DOWN, self.on_down)
        self.accel_map.map_key(TUI_KEY_UP, self.on_up)
        self.accel_map.map_key(as_key(' '), self.on_space)
        self.accel_map.map_keys(TUI_KEY_ENTER, self.on_enter)
        self.accel_map.map_key(as_key('q'), on_quit)

    def destroy(self, tui: TuiContext) -> None:
        '''Destroy UI widgets and bindings and set program data'''
        self.accel_map.remove_from_tui(tui)

        categories: list[Category] = []
        for menu_index, menu in enumerate(self.menus):
            for entry_index, entry in enumerate(menu.entries):
                if entry.enabled:
                    categories.append(self.classes[menu_index].categories[entry_index])

        dictionary: dict[LanguagesKey, dict[str, list[str]]] = make_language_dictionary(categories)
        if len(dictionary.keys()) == 0:
            # TODO: handle empty dictionary
            raise NotImplementedError

        self.prog_data["categories"] = categories
        self.prog_data["dictionary"] = dictionary

    def get_next_selection(self, menu_index: int, entry_index: int) -> tuple[int, int]:
        '''Get the indices for the next entry in the form'''
        assert menu_index >= 0 and menu_index < len(self.menus)
        current_menu = self.menus[menu_index]
        n_entries = len(current_menu.entries)
        if menu_index + 1 >= len(self.menus) and entry_index + 1 >= n_entries:
            return (menu_index, entry_index) # no next entry
        if entry_index + 1 >= n_entries:
            return (menu_index + 1, 0) # first entry of next menu
        return (menu_index, entry_index + 1) # next entry

    def get_prev_selection(self, menu_index: int, entry_index: int) -> tuple[int, int]:
        '''Get the indices for the previous entry in the form'''
        assert menu_index >= 0 and menu_index < len(self.menus)
        if menu_index == 0 and entry_index == 0:
            return (menu_index, entry_index) # no previous entry
        if entry_index == 0:
            # last entry of previous menu
            return (menu_index - 1, len(self.menus[menu_index - 1].entries) - 1)
        return (menu_index, entry_index - 1)

    def on_down(self, t: TuiContext):
        self.cur_menu_idx, self.cur_entry_idx = self.get_next_selection(
                self.cur_menu_idx, self.cur_entry_idx)
        x, y = self.menus[self.cur_menu_idx].entries[self.cur_entry_idx].rendered_cursor_pos
        t.move_cursor(x, y)

    def on_up(self, t: TuiContext):
        self.cur_menu_idx, self.cur_entry_idx = self.get_prev_selection(
                self.cur_menu_idx, self.cur_entry_idx)
        x, y = self.menus[self.cur_menu_idx].entries[self.cur_entry_idx].rendered_cursor_pos
        t.move_cursor(x, y)

    def on_enter(self, t: TuiContext):
        t.emit(TUI_OK_EVENT)

    def on_space(self, t: TuiContext):
        entry = self.menus[self.cur_menu_idx].entries[self.cur_entry_idx]
        entry.enabled = not entry.enabled
        t.redraw()
        t.move_cursor(*entry.rendered_cursor_pos)

class LanguageSelectionScreen(ScreenBase):
    '''Screen for selecting languages

    If there is only one language avaialable then it is selected and this class
    emits an Ok event'''

    def __init__(self, prog_data: dict):
        self.prog_data = prog_data
        self.dictionary: dict[LanguagesKey, dict[str, list[str]]] = prog_data["dictionary"]
        self.languages_keys: list[LanguagesKey] = list(self.dictionary.keys())

        self.screen: MenuScreen | None
        if len(self.languages_keys) == 1:
            self.prog_data["languages"] = self.languages_keys[0]
            self.screen = None
        else:
            self.screen =  MenuScreen(
                    prog_data=self.prog_data,
                    items=self.languages_keys,
                    title="Select a language pair:",
                    item_display_fn=lambda k: f"{k[1]} -> {k[0]}")

    def draw(self, tui: TuiContext) -> None:
        '''Draw calls to render screen if screen was set'''
        if self.screen is None:
            return

        self.screen.draw(tui)

    def create_bindings(self, tui: TuiContext) -> None:
        '''Create bindings for screen if screen was set, otherwise emit Ok event
        to shortcut selection'''
        if self.screen is None:
            tui.emit(TUI_OK_EVENT)
            return

        self.screen.create_bindings(tui)

    def destroy(self, tui: TuiContext) -> None:
        '''Destroy menu screen if screen was set'''
        if self.screen is not None:
            self.screen.destroy(tui)
            self.prog_data["languages"] = self.prog_data["selection"]

        categories: list[Category] = self.prog_data["categories"]
        dictionary: dict[LanguagesKey, dict[str, list[str]]] = self.prog_data["dictionary"]
        languages: LanguagesKey = self.prog_data["languages"]
        self.prog_data["session"] = PracticeSession(
                categories, languages, dictionary[languages])

class RoundsSelectionScreen(ScreenBase):
    '''Menu screen for picking the number of rounds to play'''

    def __init__(self, prog_data: dict):
        self.prog_data = prog_data
        self.screen = MenuScreen(
                self.prog_data,
                items=(5, 10, 20, 50),
                title="How many rounds?",
                item_display_fn=lambda n: f"{n} rounds",
                start_index=1)

    def draw(self, tui: TuiContext) -> None:
        self.screen.draw(tui)

    def create_bindings(self, tui: TuiContext) -> None:
        self.screen.create_bindings(tui)

    def destroy(self, tui: TuiContext) -> None:
        self.screen.destroy(tui)
        self.prog_data["rounds_left"] = self.prog_data["selection"]

GAME_GUESSING         = 0
GAME_WAITING_TO_RETRY = 1
GAME_WORD_GUESSED     = 2
GAME_WORD_MISSED      = 3

class PlayMemorizeScreen(ScreenBase):
    '''Main game screen'''

    def __init__(self, prog_data: dict):
        self.prog_data = prog_data
        self.session: PracticeSession = self.prog_data["session"]
        self.rounds_left: int = self.prog_data["rounds_left"]

        if self.rounds_left > 0:
            self.initialise_game_variables()

    def initialise_game_variables(self):
        '''Initialise variables for game; only run if there are ronuds left'''
        self.word = get_random_word(self.session)
        self.answers = self.session.dictionary[self.word]
        self.session.total_tests += 1

        self.guesses_left = 3

        self.title = self.display_title()
        self.answer_prompt = f"Answer ({self.display_guesses(self.guesses_left)} left):"
        self.answer_response = ""
        self.feedback_1 = ""
        self.feedback_2 = ""
        self.state = GAME_GUESSING

    def draw(self, tui: TuiContext) -> None:
        '''Draw calls to render if any rounds left'''
        if self.rounds_left == 0:
            return

        tui.clear_screen()
        tui.begin_draw()

        self.layout = Layout(centered_x=True, centered_y=True, min_width=50)
        self.layout.add_to_tui(tui)
        self.layout.add_evaluated_text(lambda: self.title)
        self.layout.add_text("")
        self.layout.add_text("Your word is:")
        self.layout.add_text(self.word)
        self.layout.add_text("")
        self.layout.add_evaluated_text(lambda: self.answer_prompt)

        self.entry = self.layout.add_evaluated_text(lambda: self.answer_response)

        self.layout.add_text("")
        self.layout.add_evaluated_text(lambda: self.feedback_1)
        self.layout.add_evaluated_text(lambda: self.feedback_2)

        tui.end_draw()
        tui.refresh_screen()

        cursor_x = self.entry.start_x
        cursor_y = self.entry.start_y
        tui.move_cursor(cursor_x, cursor_y)

    def create_bindings(self, tui: TuiContext) -> None:
        '''Create bindings for event handlers'''
        if self.rounds_left == 0:
            self.prog_data["next_state_override"] = SELECT_MORE_ROUNDS_STATE
            tui.emit(TUI_OK_EVENT)
            return

        tui.add_callback(TUI_KEY_EVENT, self.on_entry_key_press)
        tui.add_callback("text_changed", self.on_text_changed)
        tui.add_callback("submit", self.on_submit)
        tui.add_callback("retry", self.on_retry)
        tui.add_callback("finish", self.on_finish)

        self.accel_map = AcceleratorMap()
        self.accel_map.add_to_tui(tui)
        self.accel_map.map_keys(TUI_KEY_ENTER, self.on_enter)

    def destroy(self, tui: TuiContext) -> None:
        '''Destroy UI components and set program data'''
        if self.rounds_left == 0:
            return

        tui.remove_callback(TUI_KEY_EVENT, self.on_entry_key_press)
        tui.remove_callback("text_changed", self.on_text_changed)
        tui.remove_callback("submit", self.on_submit)
        tui.remove_callback("retry", self.on_retry)
        tui.remove_callback("finish", self.on_finish)
        self.accel_map.remove_from_tui(tui)

        self.prog_data["rounds_left"] = self.rounds_left - 1

    def move_cursor_to_entry(self, t: TuiContext):
        t.move_cursor(x=self.entry.start_x + len(self.answer_response),
                      y=self.entry.start_y)

    def on_entry_key_press(self, t: TuiContext, k: TuiKey) -> bool:
        if self.state != GAME_GUESSING:
            return True

        key_str = key_to_str(k)
        if k == TUI_KEY_BACKSPACE and len(self.answer_response) == 0:
            pass
        elif k == TUI_KEY_BACKSPACE:
            t.clear_screen() # anticipate needing to redraw
            self.answer_response = self.answer_response[:-1]
            t.emit("text_changed")
        elif len(key_str) > 1: # key is special key
            pass
        else:
            self.answer_response = self.answer_response + key_str
            t.emit("text_changed")
        return True

    def on_text_changed(self, t: TuiContext, _) -> bool:
        t.redraw()
        self.move_cursor_to_entry(t)
        return True

    def on_enter(self, t: TuiContext):
        if len(self.answer_response) == 0:
            return

        if self.state == GAME_GUESSING:
            t.emit("submit")
        elif self.state == GAME_WAITING_TO_RETRY:
            t.emit("retry")
        elif self.state == GAME_WORD_GUESSED:
            t.emit("finish")
        elif self.state == GAME_WORD_MISSED:
            t.emit("finish")
        else:
            raise RuntimeError(f"Unknown state in PlayMemorizeScreen: {self.state}")

    def correct(self, t: TuiContext):
        self.session.streak += 1
        self.feedback_1 = congratulation()
        if len(self.answers) > 1:
            other_answers = ( answer
                             for answer in self.answers
                             if answer != self.answer_response)
            self.feedback_2 = f"Other answers could have been {' or '.join(other_answers)}"

        self.state = GAME_WORD_GUESSED
        t.redraw()
        self.move_cursor_to_entry(t)

    def wrong(self, t: TuiContext):
        old_streak = self.session.streak
        self.session.streak = 0
        if old_streak >= MINIMUM_STREAK_DISPLAY:
            self.title = self.display_title_lost_streak(old_streak)

        self.guesses_left -= 1
        if self.guesses_left == 0:
            self.answer_prompt = f"Answer ({self.display_guesses(self.guesses_left)} left):"
            self.feedback_1 = comiseration()
            if len(self.answers) > 1:
                self.feedback_2 = f"The correct answers were {' or '.join(self.answers)}"
            else:
                self.feedback_2 = f"The correct answer was {self.answers[0]}"
            self.state = GAME_WORD_MISSED
            t.redraw()
            self.move_cursor_to_entry(t)

        else:
            self.answer_prompt = f"Answer ({self.display_guesses(self.guesses_left)} left):"
            self.feedback_1 = "Incorrect"
            self.feedback_2 = "Press Enter to retry..."
            t.clear_screen()
            t.redraw()
            self.move_cursor_to_entry(t)
            self.state = GAME_WAITING_TO_RETRY

            if self.word not in self.session.practice_words:
                self.session.practice_words.append(self.word)

    def on_submit(self, t: TuiContext, _) -> bool:
        if self.answer_response.lower().strip() in self.answers:
            self.correct(t)
        else:
            self.wrong(t)
        return True

    def on_retry(self, t: TuiContext, _) -> bool:
        self.answer_prompt = f"Answer ({self.display_guesses(self.guesses_left)} left):"
        self.answer_response = ""
        self.feedback_1 = ""
        self.feedback_2 = ""
        self.state = GAME_GUESSING
        t.clear_screen()
        t.redraw()
        self.move_cursor_to_entry(t)
        return True

    def on_finish(self, t: TuiContext, _) -> bool:
        if self.state == GAME_WORD_MISSED and self.word not in self.session.missed_words:
            self.session.missed_words.append(self.word)

        t.emit(TUI_OK_EVENT)
        return True

    def display_guesses(self, guesses: int) -> str:
        '''String display helper for number of guesses left'''
        if guesses > 1:
            return f"{guesses} guesses"
        if guesses == 1:
            return "1 guess"
        return "no guesses"

    def display_title(self) -> str:
        '''String display helper for title'''
        if self.session.streak < MINIMUM_STREAK_DISPLAY:
            return f"Test #{self.session.total_tests}"
        return f"Test #{self.session.total_tests} | Streak: {self.session.streak}"

    def display_title_lost_streak(self, old_streak: int) -> str:
        '''String display helper for title after lost streak'''
        return f"Test #{self.session.total_tests} | Streak of {old_streak} lost..."

class MoreRoundsSelectionScreen(ScreenBase):
    '''Menu for selecting more rounds after the game ends'''

    def __init__(self, prog_data: dict):
        self.prog_data = prog_data
        self.screen = MenuScreen(
                self.prog_data,
                items=(0, 5, 10, 20, 50),
                title="How many rounds?",
                item_display_fn=lambda n: f"{n} rounds" if n > 0 else "Finish")

    def draw(self, tui: TuiContext) -> None:
        self.screen.draw(tui)

    def create_bindings(self, tui: TuiContext) -> None:
        self.screen.create_bindings(tui)

    def destroy(self, tui: TuiContext) -> None:
        self.screen.destroy(tui)
        selection = self.prog_data["selection"]
        self.prog_data["rounds_left"] = selection

        # TODO change when event data is implemented
        if selection == 0:
            self.prog_data["next_state_override"] = SUMMARY_STATE

class SummaryScreen(ScreenBase):
    '''Summary screen at the end of a session'''

    def __init__(self, prog_data: dict):
        self.prod_data = prog_data
        self.session: PracticeSession = self.prod_data["session"]

    def draw(self, tui: TuiContext) -> None:
        tui.clear_screen()
        tui.begin_draw()
        self.layout = Layout(centered_x=True, centered_y=True, min_width=50)
        self.layout.add_to_tui(tui)
        self.layout.add_text(f"Total tests: {self.session.total_tests}")

        self.layout.add_text("")
        if len(self.session.missed_words) == 0:
            self.layout.add_text("There were no missed words")
        else:
            self.layout.add_text("Missed words:")
            for word in self.session.missed_words:
                self.layout.add_text(f"    {word}")

        self.layout.add_text("")
        if len(self.session.practice_words) == 0:
            self.layout.add_text("There are no words to practice")
        else:
            self.layout.add_text("Words to practice:")
            for word in self.session.practice_words:
                self.layout.add_text(f"    {word}")

        self.layout.add_text("")
        self.layout.add_text("Press any key to quit...")

        tui.end_draw()
        tui.refresh_screen()

    def create_bindings(self, tui: TuiContext) -> None:
        tui.add_callback(TUI_KEY_EVENT, self.on_key_press)

    def on_key_press(self, t: TuiContext, _):
        t.emit(TUI_OK_EVENT)
        return True

    def destroy(self, tui: TuiContext) -> None:
        tui.remove_callback(TUI_KEY_EVENT, self.on_key_press)

def main_tui_mode(stdscr: curses.window, classes: list[Class]) -> None:
    tui = TuiContext(stdscr)
    accel_map = AcceleratorMap(key_map={
        as_ctrl_key('c'): on_quit })
    accel_map.add_to_tui(tui)

    prog = TuiProgram(tui, {"classes": classes})
    prog.define_screen(TUI_BEGIN_STATE, CategorySelectionScreen, SELECT_LANG_STATE)
    prog.define_screen(SELECT_LANG_STATE, LanguageSelectionScreen, SELECT_ROUNDS_STATE)
    prog.define_screen(SELECT_ROUNDS_STATE, RoundsSelectionScreen, PLAY_MEMORIZE_STATE)
    prog.define_screen(PLAY_MEMORIZE_STATE, PlayMemorizeScreen, PLAY_MEMORIZE_STATE)
    prog.define_screen(SELECT_MORE_ROUNDS_STATE, MoreRoundsSelectionScreen, PLAY_MEMORIZE_STATE)
    prog.define_screen(SUMMARY_STATE, SummaryScreen, TUI_END_STATE)
    prog.run()

    accel_map.remove_from_tui(tui)

def run_main_tui_mode(classes: list[Class]) -> None:
    '''Run tui mode'''
    curses.wrapper(main_tui_mode, classes)

