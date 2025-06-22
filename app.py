from PyQt5 import QtCore, QtGui
from PyQt5.QtWidgets import QMainWindow
from models import AppContext
from modes.all_modes import Modes
from modes.lyrics_mode import LyricsMode
from modes.waiting_mode import WaitingMode
from modes.visualizer_mode import VisualizerMode
from modes.now_playing_mode import NowPlayingMode
from itertools import cycle

import audio.processing as ap


class KioskApp(QMainWindow):
    def __init__(self, context: AppContext, dev_mode: bool = False):
        super().__init__()

        self.setWindowTitle("Music Kiosk")
        self.showFullScreen()

        self.context = context
        self.dev_mode = dev_mode

        self.mode_switch_timer = QtCore.QTimer()
        self.mode_switch_timer.setInterval(60000)  # One minute, in milliseconds
        self.mode_switch_timer.timeout.connect(self.__timer_auto_switch)
        self.mode_switch_timer.start()

        self.audio_update_timer = QtCore.QTimer()
        self.audio_update_timer.setInterval(33)  # Every 33ms, which is around 30FPS
        self.audio_update_timer.timeout.connect(self.__update_loop)
        self.audio_update_timer.start()

        cyclable_modes = [mode for mode in Modes if mode != Modes.Waiting]
        self.mode_cycle = cycle(cyclable_modes)
        self.modes = {
            Modes.WAITING: WaitingMode(context),
            Modes.NOW_PLAYING: NowPlayingMode(context),
            Modes.LYRICS: LyricsMode(context),
            Modes.VISUALIZER: VisualizerMode(context)
        }
        self.current_mode_enum = Modes.WAITING
        self.current_mode = self.modes[self.current_mode_enum]

        if dev_mode:
            self.handle_input = self.__handle_keyboard
        else:
            self.handle_input = self.__gpio_handler

    def keyPressEvent(self, event):
        """ Overloaded method for key presses, only used when dev_mode is True. """
        if self.dev_mode:
            self.handle_input(event)

    def paintEvent(self, event):
        """ Overloaded method for paint events, calls the current mode's render method. """
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtCore.Qt.black)

        self.current_mode.render(painter)

    def switch_mode(self, mode: Modes):
        """ Switches the current mode based on given mode number. """
        self.current_mode_enum = mode
        self.current_mode = self.modes[self.current_mode_enum]

        # Add transition here

        if self.dev_mode:
            print(f"Current mode switched to {mode}")

    def __handle_keyboard(self, event):
        """ Binds mode changes to key presses while in dev_mode. """
        if event.key() == QtCore.Qt.Key_1:
            self.switch_mode(Modes.NOW_PLAYING)
        elif event.key() == QtCore.Qt.Key_2:
            self.switch_mode(Modes.LYRICS)
        elif event.key() == QtCore.Qt.Key_3:
            self.switch_mode(Modes.VISUALIZER)

    def __gpio_handler(self, pin: int):
        """ Binds actions to GPIO pins. """
        pass

    def __timer_auto_switch(self):
        """ Switches mode based on timer calculation. """
        self.switch_mode(next(self.mode_cycle))

    def __update_loop(self):
        """ Gathers latest audio data and processes it, stores it in the current context, and redraws the window. """
        audio_data = self.context.audio.get_audio_data()
        computed_data = ap.compute_fft(audio_data)

        self.context.audio_state.volume_rms = ap.calculate_rms(audio_data)
        self.context.audio_state.frequency_bins = ap.group_frequencies(
            computed_data,
            32,
            self.context.config.sample_rate
        )

        self.update()
