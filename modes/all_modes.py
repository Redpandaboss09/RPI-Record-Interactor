from enum import Enum, unique

#TODO CATCH VALUE ERROR FROM UNIQUE
@unique
class Modes(Enum):
    """
        Enumeration that stores all available display modes. New modes should be added here, and given a
        new UNIQUE id number. WAITING should ALWAYS be 0, since that is used by the program but inaccessible manually
        by the user.
    """
    WAITING = 0
    NOW_PLAYING = 1
    LYRICS = 2
    VISUALIZER = 3
