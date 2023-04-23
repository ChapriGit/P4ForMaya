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
from P4 import P4, P4Exception
from maya import cmds


class MessageType(Enum):
    LOG = 0
    WARNING = 1
    ERROR = 2

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

    def _send_to_log(self, log_message, msg_type):
        self._handler.send_to_log(log_message, msg_type)

    @abstractmethod
    def _create_ui(self, master_layout):
        pass

    @abstractmethod
    def get_pretty_name(self):
        pass


# TODO: Password stuff
class Connector(P4MayaModule):
    """
    Initialises and checks the Perforce connection.
    """
    def __init__(self, pref_handler, master_layout):
        super().__init__(master_layout)
        self.__pref_handler = pref_handler
        self.__log = []

    def set_handler(self, handler):
        self._handler = handler
        self.__set_p4(False)
        self._handler.set_connect(self)

    def __connect(self):
        port = cmds.textField(self.__port, q=True, text=True)
        user = cmds.textField(self.__user, q=True, text=True)
        client = cmds.textField(self.__workspace, q=True, text=True)

        if port == "" or user == "" or client == "":
            self.log_connection("Please fill in all the fields.")
            return

        p4 = P4()  # Create the P4 instance
        p4.port = port
        p4.user = user
        p4.client = client

        incorrect_data = False
        incorrect_key = ""

        try:
            p4.connect()
            info = p4.run("info")
            for key in info[0]:
                if info[0][key] == "*unknown*":
                    incorrect_data = True
                    incorrect_key = "user" if key == "userName" else "workspace"
                    break
            print(p4.run("login", "-s"))
            p4.disconnect()

            if not incorrect_data:
                log_msg = f"Connected to P4 server {port} as {user} on {client}."
                msg_type = MessageType.LOG
            else:
                log_msg = f"The {incorrect_key} given does not exist. Please try again."
                msg_type = MessageType.ERROR
        except P4Exception as inst:
            log_msg = "\n".join(inst.errors)
            if log_msg == "":
                log_msg = "The server given does not exist. Please try again."
            msg_type = MessageType.ERROR

        self.log_connection(log_msg)

        self.__set_p4(msg_type is not MessageType.ERROR)
        self._send_to_log(log_msg, msg_type)

    def __disconnect(self):
        self.__set_p4(False)
        self.log_connection("Disconnected from P4.")
        self._send_to_log("Disconnected from P4.", MessageType.LOG)

    def log_connection(self, log_message):
        self.__log.insert(0, ">> " + log_message)
        if len(self.__log) > 50:
            self.__log.remove(0)
        log = "\n\n".join(self.__log)
        cmds.scrollField(self.__log_display, e=True, text=log)

    def __set_p4(self, connected):
        port = cmds.textField(self.__port, q=True, text=True)
        user = cmds.textField(self.__user, q=True, text=True)
        client = cmds.textField(self.__workspace, q=True, text=True)

        self._handler.change_connection(port, user, client, connected)

    def __update_prefs(self):
        pass

    def _create_ui(self, master_layout):
        self._ui = cmds.formLayout(p=master_layout)
        form = cmds.formLayout(w=350)

        port, user, client, avail_clients = self.__get_default_values()
        height = 20
        server_label = cmds.text(l="Server: ", h=height)
        self.__port = cmds.textField(h=height, text=port)
        user_label = cmds.text(l="User: ", h=height)
        self.__user = cmds.textField(h=height, text=user)
        wsp_label = cmds.text(l="Workspace: ", h=height)
        self.__workspace = cmds.textField(h=height, text=client)

        margin_side = 35
        margin_middle = 10
        margin_top = 5
        padding_top = 20
        cmds.formLayout(form, e=True, af={(server_label, "left", margin_side), (self.__port, "right", margin_side),
                                          (user_label, "left", margin_side), (self.__user, "right", margin_side),
                                          (wsp_label, "left", margin_side), (self.__workspace, "right", margin_side),
                                          (server_label, "top", padding_top), (self.__port, "top", padding_top)},
                        ac={(self.__port, "left", margin_middle, server_label),
                            (self.__user, "left", margin_middle, user_label),
                            (self.__workspace, "left", margin_middle, wsp_label),
                            (self.__user, "top", margin_top, self.__port),
                            (self.__workspace, "top", margin_top, self.__user),
                            (user_label, "top", margin_top, server_label),
                            (wsp_label, "top", margin_top, user_label)})

        available_wsp_label = cmds.text(l="Available workspaces", align="left", h=height)
        wsp_menu = cmds.optionMenu(h=height, w=230,
                                   cc=lambda new_client: cmds.textField(self.__workspace, e=True, text=new_client))
        cmds.menuItem(label='')
        for c in avail_clients:
            cmds.menuItem(label=c)

        buttons = cmds.rowLayout(nc=2)
        cmds.button(l="Connect to P4", bgc=[0.2, 0.85, 0.98], w=100, c=lambda _: self.__connect())
        cmds.button(l="Disconnect", c=lambda _: self.__disconnect())

        cmds.formLayout(form, e=True, af={(available_wsp_label, "left", margin_side), (wsp_menu, "right", margin_side),
                                          (wsp_menu, "left", margin_side*2), (buttons, "right", margin_side),
                                          (buttons, "bottom", padding_top)},
                        ac={(available_wsp_label, "top", margin_top, self.__workspace),
                            (wsp_menu, "top", margin_top, available_wsp_label), (buttons, "top", margin_top, wsp_menu)})

        label = cmds.text(l="Connection Log:", p=self._ui)
        self.__log_display = cmds.scrollField(h=200, wordWrap=True, ed=False, p=self._ui)

        cmds.formLayout(self._ui, e=True, af={(form, "top", 0), (self.__log_display, "bottom", padding_top),
                                              (form, "left", 0), (form, "right", 0),
                                              (self.__log_display, "left", 15), (self.__log_display, "right", 15),
                                              (label, "left", 20)},
                        ac={(self.__log_display, "top", 5, label), (label, "top", 5, form)})

    def __get_default_values(self):
        p4 = P4()
        port = str(p4.env("P4PORT") or '')
        user = str(p4.env("P4USER") or '')
        client = ""
        p4.connect()
        avail_clients = p4.run("clients", "-u", user)
        p4.disconnect()

        clients = []
        for c in avail_clients:
            if c.get("Host") == p4.host:
                clients.append(c.get("client"))

        return port, user, client, clients

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
        return "File History"


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
# ############################################ DOCKABLE BAR ############################################## #
############################################################################################################

# TODO: Open the actual settings window when pressing buttons
class P4Bar(object):
    __BAR_NAME = "P4ForMaya"

    def __init__(self):
        self.__handler = None
        self.__docked_window = self.__BAR_NAME
        self.__log_window = ""
        self.__ui = ""

        self.__log_field = ""
        self.__connected_icon = ""
        self.__connected_text = ""
        self.__log = []
        self.__log_field = ""
        self.__log_display = ""

        self.__create_ui()
        self.__create_log_window()

    def set_handler(self, handler):
        self.__handler = handler
        cmds.iconTextButton(self.__connected_icon, e=True, c=self.__handler.open_window)

    def set_connected(self, connected: bool):
        if connected:
            cmds.iconTextButton(self.__connected_icon, e=True, i="confirm.png")
            cmds.text(self.__connected_text, e=True, l="Connected")
        else:
            cmds.iconTextButton(self.__connected_icon, e=True, i="SP_MessageBoxCritical.png")
            cmds.text(self.__connected_text, e=True, l="Not Connected")

    def add_to_log(self, log_message, msg_type: MessageType):
        cmds.textField(self.__log_field, e=True, text=log_message)
        colours = [[0.17, 0.17, 0.17], [0.88, 0.70, 0.30], [1, 0.48, 0.48]]
        cmds.textField(self.__log_field, e=True, bgc=colours[msg_type.value])

        self.__update_log(log_message, msg_type)

    def __create_ui(self):
        self.__docked_window = cmds.window(title="P4 For Maya")
        self.__ui = cmds.formLayout()

        if cmds.dockControl(self.__BAR_NAME, q=True, ex=True):
            cmds.deleteUI(self.__BAR_NAME)
        cmds.dockControl(self.__BAR_NAME, content=self.__docked_window, a="bottom", allowedArea=["bottom", "top"],
                         l="P4 For Maya", ret=False)

        connected = cmds.rowLayout(nc=2)
        cmds.popupMenu(b=3)
        cmds.menuItem(l="Change Connection")
        cmds.menuItem(d=True)
        cmds.menuItem(l="See Changelist")
        cmds.menuItem(l="File History")
        cmds.menuItem(l="Checks")
        self.__connected_icon = cmds.iconTextButton(style="iconOnly", i="confirm.png", h=18, w=18,)
        self.__connected_text = cmds.text(l="Connected")

        log = cmds.rowLayout(nc=3, p=self.__ui)
        cmds.text(l="P4:", w=50)
        self.__log_field = cmds.textField(ed=False, w=750, font="smallPlainLabelFont", text="test",
                                          bgc=[0.17, 0.17, 0.17])
        cmds.iconTextButton(style="iconOnly", i="futurePulldownIcon.png", h=17, w=17,
                            c=self.__show_full_log)

        cmds.formLayout(self.__ui, e=True, af={(log, "left", 0), (connected, "right", 10)})

    # TODO: Make it scaleable/Copyable/whatever :P
    def __create_log_window(self):
        self.__log_window = cmds.window(w=400, h=500, title="P4 Log", ret=True)
        cmds.columnLayout(adj=True)
        self.__log_display = cmds.scrollField(h=500, wordWrap=True, ed=False)

    def __update_log(self, log_message, msg_type):
        self.__log.append(f">> [{msg_type.name}] " + log_message)
        if len(self.__log) > 50:
            self.__log.remove(0)
        log = "\n\n".join(self.__log)
        cmds.scrollField(self.__log_display, e=True, text=log)

    def __show_full_log(self):
        cmds.showWindow(self.__log_window)

    def __log_test(self):
        self.add_to_log("This is a warning, because warnings on line 500, I think. Not sure, because I didn't do "
                        "anything", MessageType.WARNING)
        self.add_to_log("Logging stuff here, yay!", MessageType.LOG)
        self.add_to_log("More logging, logging is fun", MessageType.LOG)
        self.add_to_log("WARNIIIIIING, line 4954, in file khdfg/dfg/dfg/h/dfg.ma, have fun", MessageType.WARNING)
        self.add_to_log("Last log, I swear", MessageType.LOG)


############################################################################################################
# ############################################# CONTROLLERS ############################################## #
############################################################################################################

class P4MayaControl:
    """
    Base class of P4 for Maya
    """
    def __init__(self, window, layout, bar: P4Bar):
        self.p4 = P4()
        self.window = window
        self.__bar = bar
        self.__connect = None

        row = cmds.rowLayout(p=layout, nc=2)
        self.__connected_icon = cmds.iconTextButton(style="iconOnly", i="confirm.png", h=18, w=18, )
        self.__connected_text = cmds.text(l="Connected")
        cmds.formLayout(layout, e=True, af={(row, "bottom", 10), (row, "right", 10)})

    def set_connect(self, connect):
        self.__connect = connect

    def open_window(self):
        cmds.showWindow(self.window)

    def change_connection(self, port, user, client, connected):
        self.p4.port = port
        self.p4.user = user
        self.p4.client = client

        self.__set_connected(connected)

    def send_to_log(self, log_message, msg_type):
        self.__bar.add_to_log(log_message, msg_type)

    def __set_connected(self, connected: bool):
        if connected:
            cmds.iconTextButton(self.__connected_icon, e=True, i="confirm.png")
            cmds.text(self.__connected_text, e=True, l="Connected")
        else:
            cmds.iconTextButton(self.__connected_icon, e=True, i="SP_MessageBoxCritical.png")
            cmds.text(self.__connected_text, e=True, l="Not Connected")

        self.__bar.set_connected(connected)


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
        window, layout, modules = self.__create_window()
        bar = P4Bar()
        controller = P4MayaControl(window, layout, bar)
        bar.set_handler(controller)

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
        window = cmds.window(title="P4 Settings and Actions", width=300, height=500, ret=True)
        master_layout = cmds.formLayout(w=350)
        tabs_layout = cmds.tabLayout(p=master_layout)
        cmds.formLayout(master_layout, e=True, af=[(tabs_layout, "top", 0),
                                                   (tabs_layout, "right", 0),
                                                   (tabs_layout, "left", 0)])

        modules = cls.__create_modules(tabs_layout)
        for m in modules:
            ui = m.get_ui()
            cmds.tabLayout(tabs_layout, e=True, tabLabel=(ui, m.get_pretty_name()))

        cmds.tabLayout(tabs_layout, e=True, mt=[2, 4])

        return window, master_layout, modules


P4MayaFactory()
