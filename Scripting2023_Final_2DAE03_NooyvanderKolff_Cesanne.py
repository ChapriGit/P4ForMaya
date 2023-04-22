"""
P4 For Maya: Automatic adding and checking out of Perforce Maya files from within Maya.
    Core functionality:
        - Connecting
            Errors:
                - Workspace does not exist
                - User does not exist
                - Can't connect to server
                - ...
        - Intercepting saving to add and/or check out files
            Errors:
                - Someone else has the file checked out (In our case always exclusive, though technically .ma is text..)
    Extra functionality:
        - Revert current changes
            Errors:
                - File not saved yet -> Not on P4
        - Submitting changed files
            - Add description
            - Deselect files for submit
            - Keeps track of changelist even when Maya closed in between
            - Creates new one if old one got submitted or is not pending anymore
            Errors:
                - I don't really know yet, but probably a lot of them :P
        - Checking of conventions
            - Naming conventions: Regex
            - Geometry:
                - Non-manifold
                - ngons
                - Overlapping
                - Zero-length
                - Concave
                - ...

                - Intersecting
            - Textures on P4
        - Rolling back files to previous versions
        - Get Latest of file

"""

from abc import ABC, abstractmethod
from enum import Enum
from maya import cmds


class MessageType(Enum):
    LOG = 1
    WARNING = 2
    ERROR = 3

############################################################################################################
# ############################################### MODULES ################################################ #
############################################################################################################


class P4MayaModule(ABC):
    def __init__(self, master_layout):
        self._handler = None
        self._ui = ""
        self._create_ui(master_layout)

    def set_handler(self, handler):
        self._handler = handler

    def get_ui(self):
        return self._ui

    def __get_p4(self):
        pass

    def __send_to_log(self, log_message, msg_type):
        pass

    @abstractmethod
    def _create_ui(self, master_layout):
        pass

    @abstractmethod
    def get_pretty_name(self):
        pass


class P4Bar(P4MayaModule):
    def __init__(self, master_layout):
        super().__init__(master_layout)

    def set_connected(self, connected: bool):
        pass

    def __add_to_log(self, log_message):
        pass

    def _create_ui(self, master_layout):
        self._ui = cmds.columnLayout(adj=True)

    def get_pretty_name(self):
        return "P4 For Maya"


class Connector(P4MayaModule):
    """
    Initialises and checks the Perforce connection.
    """
    def __init__(self, pref_handler, master_layout):
        super().__init__(master_layout)
        self.__pref_handler = pref_handler

        self.__set_p4()

    def set_handler(self, handler):
        super().set_handler(handler)
        self.__set_p4()

    def __connect(self):
        pass

    def __disconnect(self):
        pass

    def __log_error(self, log_message):
        pass

    def check_connection(self):
        pass

    def __set_p4(self):
        pass

    def __update_prefs(self):
        pass

    def _create_ui(self, master_layout):
        self._ui = cmds.columnLayout(adj=True, p=master_layout)

    def get_pretty_name(self):
        return "Connect"


class ChangeLog(P4MayaModule):
    def __init__(self, checks, master_layout):
        super().__init__(master_layout)
        self.__checks = checks

    def __get_changelist(self):
        pass

    def __refresh_changelist(self):
        pass

    def __submit(self):
        pass

    def _create_ui(self, master_layout):
        self._ui = cmds.columnLayout(adj=True, p=master_layout)

    def get_pretty_name(self):
        return "Changelog"


class Rollback(P4MayaModule):
    def __init__(self, master_layout):
        super().__init__(master_layout)

    def __get_history(self):
        pass

    def __rollback(self, revision):
        pass

    def __get_latest(self):
        pass

    def _create_ui(self, master_layout):
        self._ui = cmds.columnLayout(adj=True, p=master_layout)

    def get_pretty_name(self):
        return "Rollback"


class CustomSave(P4MayaModule):
    def __init__(self, pref_handler, master_layout):
        super().__init__(master_layout)
        self.pref_handler = pref_handler

    def check_open_file(self):
        pass

    def check_file(self, path):
        pass

    def __save_file(self):
        pass

    def _create_ui(self, master_layout):
        self._ui = cmds.columnLayout(adj=True, p=master_layout)

    def get_pretty_name(self):
        return "Checks"


############################################################################################################
# ############################################# CONTROLLERS ############################################## #
############################################################################################################

class P4MayaControl:
    """
    Base class of P4 for Maya
    """
    def __init__(self, window, bar):
        self.p4 = None
        self.window = window
        self.bar = bar

    def open_window(self):
        pass

    def change_connection(self, p4):
        pass

    def send_to_log(self, log_message, msg_type):
        pass


class PreferenceHandler:
    def __init__(self):
        self.pref_file = ""

    def load_pref(self, class_key, var_key):
        pass

    def set_pref(self, class_key, var_key, value):
        pass


class P4MayaFactory:
    """
    Creates the P4 For Maya Application.
    """
    def __init__(self):
        window, modules = self.__create_window()
        bar = P4Bar("")
        controller = P4MayaControl(window, bar)

        for m in modules:
            m.set_handler(controller)

    @staticmethod
    def __create_modules(tabs_layout):
        pref_handler = PreferenceHandler()
        connector = Connector(pref_handler, tabs_layout)
        checks = CustomSave(pref_handler, tabs_layout)
        changelog = ChangeLog(checks, tabs_layout)
        rollback = Rollback(tabs_layout)

        return connector, changelog, rollback, checks

    @classmethod
    def __create_window(cls):
        # window = cmds.window("P4MayaWindow", l="P4 Settings and Actions")
        window = cmds.window(title="P4 Settings and Actions", width=400, height=500)
        master_layout = cmds.formLayout()
        tabs_layout = cmds.tabLayout(p=master_layout)
        cmds.formLayout(master_layout, e=True, af=[(tabs_layout, "top", 0),
                                                   (tabs_layout, "right", 0),
                                                   (tabs_layout, "left", 0)])

        modules = cls.__create_modules(tabs_layout)
        for m in modules:
            ui = m.get_ui()
            cmds.tabLayout(tabs_layout, e=True, tabLabel=(ui, m.get_pretty_name()))

        return window, modules


P4MayaFactory()
