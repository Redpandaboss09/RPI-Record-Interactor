from protocols import DisplayMode
from models import AppContext
from PyQt5 import QtCore, QtGui


class LyricsMode(DisplayMode):
    def __init__(self, context: AppContext):
        self.context = context

    def update(self, dt: float) -> None:
        pass

    def render(self, painter: QtGui.QPainter, rect: QtCore.QRect):
        painter.setPen(QtGui.QPen(QtCore.Qt.white))
        painter.setFont(QtGui.QFont("Arial", 24))
        painter.drawText(rect, QtCore.Qt.AlignCenter, "Lyrics Mode")