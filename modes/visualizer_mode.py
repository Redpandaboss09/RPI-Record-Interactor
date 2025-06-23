from protocols import DisplayMode
from models import AppContext
from PyQt5 import QtCore, QtGui, QtWidgets


class VisualizerMode(DisplayMode):
    def __init__(self, context: AppContext):
        self.context = context

    def update(self, dt: float):
        pass

    def render(self, painter: QtGui.QPainter, rect: QtCore.QRect):
        if self.context.audio_state.frequency_bins is None or len(self.context.audio_state.frequency_bins) == 0:
            return

        # Simple bar visualizer
        bins = self.context.audio_state.frequency_bins
        bar_width = rect.width() // len(bins)

        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QBrush(QtCore.Qt.green))

        for i, magnitude in enumerate(bins):
            bar_height = int(magnitude / 100 * rect.height())
            bar_height = max(0, min(bar_height, rect.height()))

            x = i * bar_width
            y = rect.height() - bar_height

            painter.drawRect(x, y, bar_width - 2, bar_height)