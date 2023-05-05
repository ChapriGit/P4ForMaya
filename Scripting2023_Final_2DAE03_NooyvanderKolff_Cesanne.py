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
            - Get pending changelists - Default seems not working
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
import json
import os
import re

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from enum import Enum

from P4 import P4, P4Exception
from maya import cmds, OpenMaya as Om, mel
import maya.api.OpenMaya as Api_Om


BLUE_COLOUR = [0.2, 0.85, 0.98]         # Blue button colour.
MARGIN_SIDE = 20                        # Margin to the side of the tab layouts.


class MessageType(Enum):
    """
    An enumerator for Message Types. Can be simple logs, warnings and errors.
    """
    LOG = 0
    WARNING = 1
    ERROR = 2

############################################################################################################
# ############################################### MODULES ################################################ #
############################################################################################################


class P4MayaModule(ABC):
    """
    Abstract class defining a module of the P4 For Maya script. Every module gets a tab in the settings window.
    """
    def __init__(self, master_layout: str):
        """
        The initialisation of the abstract module.
        :param master_layout: The layout to which the module's UI needs to get attached to.
        """
        self._handler = None
        self._ui = ""
        self._create_ui(master_layout)

    def set_handler(self, handler):
        """
        Sets the handler.
        :param handler: A P4MayaControl object handling the modules of the script.
        """
        self._handler = handler

    def get_ui(self) -> str:
        """
        Returns the UI
        :return: A string containing the UI of the module.
        """
        return self._ui

    def _send_to_log(self, log_message: str, msg_type: MessageType):
        """
        Sends a message to be logged to the bar of the script.
        :param log_message: The message to be logged.
        :param msg_type: The type of message to be logged.
        """
        self._handler.send_to_log(log_message, msg_type)

    @abstractmethod
    def _create_ui(self, master_layout: str):
        """
        Creates the UI for the module attached to the master layout provided.
        :param master_layout: The layout to which the module should be attached
        """
        pass

    @abstractmethod
    def get_pretty_name(self) -> str:
        """
        Returns the pretty name of the module.
        :return: The pretty name of the module.
        """
        pass


class Connector(P4MayaModule):
    """
    Module initialising and checking the Perforce connection.
    """
    __NAME = "CONNECTOR"        # The saving name of the module.

    def __init__(self, pref_handler, master_layout: str):
        """
        Initialises the Connector modules.
        :param pref_handler: The Preference Handler to save any preferences.
        :param master_layout: The layout to which the UI of the module should be attached.
        """
        self.__pref_handler = pref_handler          # The preference handler to save and load preferences.

        self.__log = []                             # The log pertaining to the connection messages of P4.
        self.__last_checked = datetime.now()        # Last time since checking the P4 connection.
        self.__job = ""                             # The ID of the script job checking the P4 connection.

        super().__init__(master_layout)

        self.log_connection("P4 For Maya Started")

    def set_handler(self, handler):
        self._handler = handler

        # Also setting the P4 connection.
        self.__set_p4(False)

    def __check_connection(self):
        """
        Checks the P4 connection every 10 seconds. Will throw a warning and disconnect if the connection fails.
        """
        if self._handler.is_connected():
            interval = 10

            # Only check if the interval has passed.
            if datetime.now() - self.__last_checked > timedelta(seconds=interval):
                print("Checked P4 Connection")
                self.__last_checked = datetime.now()
                p4 = self._handler.p4

                try:
                    # Check the connection
                    self._handler.p4_connect(False)
                    p4.run("login", "-s")
                    self._handler.p4_release()

                except P4Exception as inst:
                    # Throw the warning and kill the script job if not able to connect anymore.
                    log_msg = "\n".join(inst.errors)
                    msg_type = MessageType.WARNING

                    self.__set_p4(False, True)
                    self._send_to_log(log_msg, msg_type)

    def __connect(self):
        """
        Tries to connect to P4 with the given port, user and workspace. If connection can be achieved, will be
        propagated to the handler.
        """
        # Get the variables necessary.
        port = cmds.textField(self.__port, q=True, text=True)
        user = cmds.textField(self.__user, q=True, text=True)
        client = cmds.textField(self.__workspace, q=True, text=True)

        # Throw an error if not everything has been filled in.
        if port == "" or user == "" or client == "":
            self.log_connection("Please fill in all the fields.")
            return

        # Set up the P4 instance.
        p4 = P4()
        p4.port = port
        p4.user = user
        p4.client = client

        # Set up the try catch.
        incorrect_data = False
        incorrect_key = ""

        try:
            # Connect and check whether the user and workspace exist.
            p4.connect()
            info = p4.run("info")
            for key in info[0]:
                if info[0][key] == "*unknown*":
                    incorrect_data = True
                    incorrect_key = "user" if key == "userName" else "workspace"
                    break

            # Check login.
            p4.run("login", "-s")
            p4.disconnect()

            # Log result.
            if not incorrect_data:
                log_msg = f"Connected to P4 server {port} as {user} on {client}."
                msg_type = MessageType.LOG
            else:
                log_msg = f"The {incorrect_key} given does not exist. Please try again."
                msg_type = MessageType.ERROR

        except P4Exception as inst:
            # Catch error and display it.
            log_msg = "\n".join(inst.errors)
            if log_msg == "":
                log_msg = "The server given does not exist. Please try again."
            msg_type = MessageType.ERROR

        # Send the message to own log.
        self.log_connection(log_msg)

        # Set up or kill the script job if necessary
        connected = msg_type is not MessageType.ERROR
        if (not self.__job) and connected:
            self.__job = cmds.scriptJob(e=["idle", lambda: self.__check_connection()])
        elif self.__job and not connected:
            cmds.scriptJob(kill=self.__job)
            self.__job = ""

        # Propagate to the handler.
        self.__set_p4(connected)
        self._send_to_log(log_msg, msg_type)

    def __disconnect(self):
        """
        Disconnect the P4 connection.
        """
        self.__set_p4(False)
        self.log_connection("Disconnected from P4.")
        self._send_to_log("Disconnected from P4.", MessageType.LOG)

    def log_connection(self, log_message: str):
        """
        Log a message on the connection log.
        :param log_message: The message to be logged.
        """
        self.__log.insert(0, ">> " + log_message)
        if len(self.__log) > 50:
            # Only keep the last 50 logs.
            self.__log.remove(0)
        log = "\n\n".join(self.__log)
        cmds.scrollField(self.__log_display, e=True, text=log)

    def __set_p4(self, connected: bool, on_job: bool = False):
        """
        Sets the P4 connection to the specified connection.
        :param connected: True if connection to P4 can be established with the given parameters.
        """
        # Get the parameters.
        port = cmds.textField(self.__port, q=True, text=True)
        user = cmds.textField(self.__user, q=True, text=True)
        client = cmds.textField(self.__workspace, q=True, text=True)

        # If connection can be established, save the values.
        if connected:
            self.__pref_handler.set_pref(self.__NAME, "P4PORT", port)
            self.__pref_handler.set_pref(self.__NAME, "P4USER", user)
            self.__pref_handler.set_pref(self.__NAME, "P4CLIENT", client)

        if not connected and self.__job and not on_job:
            cmds.scriptJob(kill=self.__job)
            self.__job = ""

        # Propagate the P4 connection and status.
        self._handler.change_connection(port, user, client, connected)

    def _create_ui(self, master_layout):
        # Setup of the overarching layout.
        self._ui = cmds.formLayout(p=master_layout)

        # Parameter section of the layout.
        form = cmds.formLayout(w=300)

        # Setup labels and text fields of the port, user and workspace.
        port, user, client, avail_clients = self.__get_default_values()
        height = 20
        server_label = cmds.text(l="Server: ", h=height)
        self.__port = cmds.textField(h=height, text=port)
        user_label = cmds.text(l="User: ", h=height)
        self.__user = cmds.textField(h=height, text=user)
        wsp_label = cmds.text(l="Workspace: ", h=height)
        self.__workspace = cmds.textField(h=height, text=client)

        margin_side = MARGIN_SIDE + 15
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

        # Create dropdown menu for workspaces.
        available_wsp_label = cmds.text(l="Available workspaces", align="left", h=height)
        wsp_menu = cmds.optionMenu(h=height, w=230,
                                   cc=lambda new_client: cmds.textField(self.__workspace, e=True, text=new_client))
        cmds.menuItem(label='')
        for c in avail_clients:
            cmds.menuItem(label=c)

        cmds.optionMenu(wsp_menu, e=True, bsp=lambda _: self.__refresh_workspaces(wsp_menu))

        # Setup of connect and disconnect button.
        buttons = cmds.rowLayout(nc=2)
        cmds.button(l="Connect to P4", bgc=BLUE_COLOUR, w=100, c=lambda _: self.__connect())
        cmds.button(l="Disconnect", c=lambda _: self.__disconnect())

        cmds.formLayout(form, e=True, af={(available_wsp_label, "left", margin_side), (wsp_menu, "right", margin_side),
                                          (wsp_menu, "left", margin_side*2), (buttons, "right", margin_side),
                                          (buttons, "bottom", padding_top)},
                        ac={(available_wsp_label, "top", margin_top, self.__workspace),
                            (wsp_menu, "top", margin_top, available_wsp_label), (buttons, "top", margin_top, wsp_menu)})

        # Setup of the log to show connection messages in.
        label = cmds.text(l="Connection Log:", p=self._ui)
        self.__log_display = cmds.scrollField(h=200, wordWrap=True, ed=False, p=self._ui)

        cmds.formLayout(self._ui, e=True, af={(form, "top", 0), (self.__log_display, "bottom", padding_top),
                                              (form, "left", 0), (form, "right", 0),
                                              (self.__log_display, "left", 15), (self.__log_display, "right", 15),
                                              (label, "left", 20)},
                        ac={(self.__log_display, "top", 5, label), (label, "top", 5, form)})

    def __get_default_values(self) -> (str, str, str, [str]):
        """
        Gets the default values for the P4 connection. With saved preferences getting the highest priority and then
        environment variables.
        :return: Returns the port, user, workspace and a list of available workspaces in that order.
        """
        p4 = P4()

        # Get the default values for port and user.
        port = self.__pref_handler.get_pref(self.__NAME, "P4PORT") or (p4.env("P4PORT") or '')
        user = self.__pref_handler.get_pref(self.__NAME, "P4USER") or str(p4.env("P4USER") or '')
        p4.port = port
        p4.user = user

        # Get the default value for the workspace.
        client = self.__pref_handler.get_pref(self.__NAME, "P4CLIENT") or ''

        # Get the available workspaces given the port and user.
        try:
            p4.connect()
            avail_clients = p4.run("clients", "-u", user)
            p4.disconnect()
            clients = []

            # Only allow workspaces that are linked to the computer being used.
            for c in avail_clients:
                if c.get("Host") == p4.host:
                    clients.append(c.get("client"))
        except P4Exception:
            clients = ["Please login to P4."]

        return port, user, client, clients

    def __refresh_workspaces(self, dropdown: str):
        """
        Refreshes the workspace dropdown with the available dropdowns.
        :param dropdown: The dropdown to create the workspace list in.
        """
        # Get the necessary variables.
        p4 = P4()
        p4.port = cmds.textField(self.__port, q=True, text=True)
        p4.user = cmds.textField(self.__user, q=True, text=True)

        # Get the available workspaces given the port and user.
        try:
            p4.connect()
            avail_clients = p4.run("clients", "-u", p4.user)
            p4.disconnect()
            clients = []

            # Only allow workspaces that are linked to the computer being used.
            for c in avail_clients:
                if c.get("Host") == p4.host:
                    clients.append(c.get("client"))
        except P4Exception:
            clients = ["Please login to P4."]

        # Add the options to the menu.
        cmds.optionMenu(dropdown, e=True, dai=True)
        cmds.menuItem(label='', p=dropdown)
        for c in clients:
            cmds.menuItem(label=c, p=dropdown)

    def get_pretty_name(self):
        return "Connect"


class ChangeLog(P4MayaModule):
    """
    Module to submit the changelog to P4. It displays the changelog and allows for a submit-message and selection of
    what to submit.
    """
    def __init__(self, master_layout):
        super().__init__(master_layout)

    def __get_changelist(self):
        pass

    def __refresh_changelist(self):
        pass

    def __submit(self):
        pass

    def _create_ui(self, master_layout):
        # Create the overarching layout.
        self._ui = cmds.formLayout(p=master_layout, w=200)
        margin_side = MARGIN_SIDE

        # Show what Changelist is being displayed.
        changelist_label = cmds.text(l="Current Changelist: ", fn="boldLabelFont")
        changelist_nr = cmds.text(l="000000", fn="fixedWidthFont")
        refresh_button = cmds.button(l="Refresh", w=70)
        cmds.formLayout(self._ui, e=True, af={(changelist_label, "left", margin_side + 5),
                                              (refresh_button, "right", margin_side), (changelist_label, "top", 20),
                                              (changelist_nr, "top", 19)},
                        ac=(changelist_nr, "left", 5, changelist_label))

        # Create the changelist itself.
        table = self.__create_table()
        cmds.formLayout(self._ui, e=True, af={(table, "left", margin_side), (table, "right", margin_side)},
                        ac={(refresh_button, "top", 10, table), (table, "top", 10, changelist_label)})

        # Allow for adding a description.
        cmds.setParent(self._ui)
        desc_label = cmds.text(l="Description:")
        self.__commit_msg = cmds.scrollField(h=100)
        submit_button = cmds.button(w=100, bgc=BLUE_COLOUR, l="Submit")
        cmds.formLayout(self._ui, e=True, af={(desc_label, "left", margin_side + 5),
                                              (submit_button, "right", margin_side),
                                              (self.__commit_msg, "left", margin_side),
                                              (self.__commit_msg, "right", margin_side),
                                              (submit_button, "bottom", 10)},
                        ac={(desc_label, "top", 5, refresh_button), (self.__commit_msg, "top", 5, desc_label),
                            (submit_button, "top", 10, self.__commit_msg)})

    # TODO: Actually fill the table.
    def __create_table(self) -> str:
        """
        Creates the changelog table.
        :return: The UI element containing the created table.
        """
        # Set up the overarching layout.
        table = cmds.scrollLayout(vsb=True, cr=True, h=200, bgc=[0.22, 0.22, 0.22])
        cmds.columnLayout(adj=True, cat=["right", 5])

        # Set up the header row.
        cmds.rowColumnLayout(nc=4, adj=3, cw=[(1, 20), (2, 40), (4, 90)], bgc=[0.17, 0.17, 0.17],
                             cat=[(1, "left", 5)], cs=[(1, 5), (2, 5), (3, 5), (4, 5)], rs=(1, 5))
        cmds.checkBox(l="")
        cmds.text(l="")
        cmds.text(l="Path", al="left")
        cmds.text(l="Last Edited", al="left")

        cmds.setParent("..")

        # Set up the actual table.
        cmds.rowColumnLayout(nc=4, adj=3, cw=[(1, 20), (2, 40), (4, 90)], cat=[(1, "left", 5)],
                             cs=[(1, 5), (2, 5), (3, 5), (4, 5)])
        cmds.checkBox(l="")
        cmds.text(l="Add")
        cmds.textField(text=r"C:\Developer\SourceArt\SM_Coffee.ma", ed=False)
        now = datetime.now()
        dt_string = now.strftime("%d/%m/%Y %H:%M")
        cmds.text(l=dt_string)

        cmds.checkBox(l="")
        cmds.text(l="Edit")
        cmds.textField(text=r"C:\Developer\SourceArt\SM_Coffee.ma", ed=False)
        now = datetime.now()
        dt_string = now.strftime("%d/%m/%Y %H:%M")
        cmds.text(l=dt_string)

        return table

    def get_pretty_name(self):
        return "Submit"


class Rollback(P4MayaModule):
    """
    Module to allow reverting the currently opened file if it is connected to the P4 file system.
    """
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
    """
    A module pertaining to saving and P4. It allows for automatic adding and checking out of files and to first check
    said file on specified points.
    """
    __NAME = "CUSTOM_SAVE"          # The module name for saving purposes.

    class CheckType(Enum):
        """
        An Enum indicating how to check for mistakes.
        """
        ERROR = 0
        WARNING = 1
        NONE = 2

    def __init__(self, pref_handler, master_layout: str):
        """
        Initialises a CustomSave module with the given preference handler in the specified layout.
        :param pref_handler: The handler that goes over storing and loading of presets.
        :param master_layout: The layout in which the module should dock its own.
        """
        # Set up the default values.
        self.__pref_handler = pref_handler
        self.__state = CustomSave.CheckType.ERROR
        self.__options = {}
        self.__options.update({
            "outside_p4": False,
            "check_naming": True,
            "naming_approach": 0,
            "naming_convention_prefix": "",
            "naming_convention_suffix": "",
            "naming_convention_regex": ".*",
            "check_directory": False,
            "directory": "",
            "non_manifold": False,
            "ngons": False,
            "concave": False,
            "frozen_transform": False,
            "centered": False
        })

        self.__load_pref()

        # Create the UI.
        super().__init__(master_layout)

        # Set up the saving callback.
        self.__cb_id = 0
        self.__create_callbacks()

    def set_handler(self, handler):
        self._handler = handler
        self._handler.manage_callback(self.__cb_id)

    def __load_pref(self):
        """
        Load the preferences into the settings of the module.
        """
        state = self.__pref_handler.get_pref(self.__NAME, "state") or 0
        self.__state = CustomSave.CheckType(state)
        options = self.__pref_handler.get_pref(self.__NAME, "options") or {}
        self.__options.update(options)

    def __set_state(self, option: int):
        """
        Set the state to the given option.
        :param option: An integer specifying the new CheckType.
        """
        self.__state = CustomSave.CheckType(option)
        self.__pref_handler.set_pref(self.__NAME, "state", self.__state.value)

        # Enable or disable the layout if no checks are necessary.
        cmds.frameLayout(self.__naming, e=True, en=not (option == 2))
        cmds.frameLayout(self.__geometry, e=True, en=not (option == 2))
        cmds.checkBox(self.__p4_checkbox, e=True, en=not (option == 2))

    def __set_variable(self, var: str, value):
        """
        Sets the specified variable to the given value.
        :param var: The variable name of the variable to change.
        :param value: The value to be given.
        """
        self.__options.update({var: value})
        self.__pref_handler.set_pref(self.__NAME, "options", self.__options)

    def _create_ui(self, master_layout):
        # Set up of the overarching layout.

        self._ui = cmds.scrollLayout(w=350, h=400, p=master_layout)
        form = cmds.formLayout(p=self._ui)

        frame = cmds.frameLayout(l="General")
        cmds.columnLayout(cat=("left", 20))
        cmds.text(l="Response to Failing Criteria:", align="left", h=20)

        # Create the radio buttons for specifying the state.
        error_check = cmds.columnLayout(adj=True, cat=("left", 15))
        options = ["Error", "Warning", "None"]
        error_options = self.create_radio_group(error_check, options, default_opt=self.__state.value)
        for i in range(3):
            cmds.iconTextRadioButton(error_options[i], e=True, onc=lambda _, j=i: self.__set_state(j))
        cmds.setParent(error_check)
        cmds.rowLayout(h=10)
        cmds.setParent("..")
        cmds.setParent("..")

        # Whether to check if saving outside a P4 structure while connected.
        self.__p4_checkbox = cmds.checkBox(l="Also check if saved outside of P4 structure",
                                           v=self.__options.get("outside_p4"),
                                           cc=lambda val: self.__set_variable("outside_p4", val))

        cmds.setParent(form)

        # Set up of the path options.
        self.__naming = cmds.frameLayout(l="Naming & Folder Structure", p=form)
        self.__create_naming_frame(self.__naming)

        # Set up of the geometry options.
        self.__geometry = cmds.frameLayout(l="Geometry", p=form)
        self.__create_geometry_frame(self.__geometry)

        # Add to form layout.
        margin_side = MARGIN_SIDE
        cmds.formLayout(form, e=True, af={(frame, "top", 15), (self.__naming, "left", margin_side),
                                          (self.__naming, "right", margin_side),
                                          (self.__geometry, "left", margin_side),
                                          (self.__geometry, "right", margin_side),
                                          (frame, "left", margin_side), (frame, "right", margin_side),
                                          (self.__geometry, "bottom", 15)},
                        ac={(self.__geometry, "top", 15, self.__naming), (self.__naming, "top", 20, frame)})

    def __create_naming_frame(self, frame: str):
        """
        Creates the frame containing the options pertaining to paths and file names.
        :param frame: The parent frame layout in which to dock the naming layout.
        """
        # Set up main layout.
        cmds.columnLayout(adj=True, p=frame)
        cmds.rowLayout(h=5)
        cmds.setParent("..")

        # Set up the naming option.
        cmds.rowLayout(nc=2, cat={(1, "left", 5), (2, "left", 5)})
        cmds.checkBox(v=self.__options.get("check_naming"), l="",
                      cc=lambda val: self.__set_variable("check_naming", val))
        cmds.text(l="Naming Convention")
        cmds.setParent("..")

        # Set up the radio buttons for specifying the naming convention
        cmds.columnLayout(adj=True, cat=("left", 25))
        collection = cmds.radioCollection()

        # Simple approach
        cmds.rowLayout(nc=2, adj=2, rat=(1, "top", 0), cat=(2, "left", 10))
        approach_simple = self.__options.get("naming_approach") == 0
        simple = cmds.radioButton(l="Simple")
        cmds.columnLayout(adj=True)
        cmds.rowLayout(nc=2, adj=2)
        cmds.text(l="Prefix: ")
        prefix = cmds.textField(text=self.__options.get("naming_convention_prefix"), pht="Anything", en=approach_simple,
                                tcc=lambda val: self.__set_variable("naming_convention_prefix", val))
        cmds.setParent("..")
        cmds.rowLayout(nc=2, adj=2)
        cmds.text(l="Suffix: ")
        suffix = cmds.textField(text=self.__options.get("naming_convention_suffix"), pht="Anything", en=approach_simple,
                                tcc=lambda val: self.__set_variable("naming_convention_suffix", val))
        cmds.setParent("..")
        cmds.radioButton(simple, e=True, cc=lambda val: self.__set_naming_simple(prefix, suffix, val))

        # Regex approach
        cmds.setParent("..")
        cmds.setParent("..")
        cmds.rowLayout(nc=2, adj=2, cat=(2, "left", 10))
        regex = cmds.radioButton(l="Regex")
        convention = cmds.textField(text=self.__options.get("naming_convention_regex"), pht="Regex",
                                    en=not approach_simple,
                                    tcc=lambda val: self.__set_variable("naming_convention_regex", val))
        cmds.radioButton(regex, e=True, cc=lambda val: self.__set_naming_regex(convention, val))

        button = simple if approach_simple else regex
        cmds.radioCollection(collection, e=True, select=button)
        cmds.setParent("..")
        cmds.setParent("..")

        # Set up the directory option.
        cmds.rowLayout(nc=4, adj=3, cat={(1, "left", 5), (2, "left", 5), (3, "left", 5), (4, "left", 5)})
        cmds.checkBox(v=self.__options.get("check_directory"), l="",
                      cc=lambda val: self.__set_variable("check_directory", val))
        cmds.text(l="Directory")
        cmds.textField(text=self.__options.get("directory"),
                       pht="Maya Files Directory", tcc=lambda val: self.__set_variable("directory", val))
        cmds.button(l="Browse")
        cmds.setParent("..")

    def __set_naming_simple(self, prefix, suffix, val):
        cmds.textField(prefix, e=True, en=val)
        cmds.textField(suffix, e=True, en=val)
        self.__set_variable("naming_approach", 0)

    def __set_naming_regex(self, regex, val):
        cmds.textField(regex, e=True, en=val)
        self.__set_variable("naming_approach", 1)

    def __create_geometry_frame(self, frame):
        """
        Creates the frame containing the options pertaining to the geometry in the file.
        :param frame: The parent frame layout in which to dock the geometry layout.
        """
        # Set up of the overarching layout/
        column = cmds.columnLayout(adj=True, cat=("left", 15), p=frame)
        cmds.rowLayout(h=5)
        cmds.setParent("..")

        # Set up of the options pertaining to shape.
        cmds.text(l="Shape:", al="left", fn="boldLabelFont", h=20)
        cmds.columnLayout(adj=True, p=column, cat=("left", 15))

        cmds.checkBox(l="Non-manifold", cc=lambda val: self.__set_variable("non_manifold", val),
                      v=self.__options.get("non_manifold"))
        cmds.checkBox(l="Ngons", cc=lambda val: self.__set_variable("ngons", val), v=self.__options.get("ngons"))
        cmds.checkBox(l="Concave Faces", cc=lambda val: self.__set_variable("concave", val),
                      v=self.__options.get("concave"))
        cmds.setParent("..")

        cmds.rowLayout(h=8, p=column)
        cmds.setParent("..")

        # Set up of the options pertaining to the transform.
        cmds.text(l="Transform:", al="left", fn="boldLabelFont", h=20)

        cmds.columnLayout(adj=True, p=column, cat=("left", 15))
        cmds.checkBox(l="Frozen Transform", cc=lambda val: self.__set_variable("frozen_transform", val),
                      v=self.__options.get("frozen_transform"))
        cmds.checkBox(l="Positioned around Center", cc=lambda val: self.__set_variable("centered", val),
                      v=self.__options.get("centered"))

    @staticmethod
    def create_radio_group(layout: str, options: [str], default_opt: int = 1, width: int = 80, offset: int = 0) \
            -> [str]:
        """
        Creates a group of radio-like buttons with the given options.
        :param layout: The parent layout.
        :param options: The labels for the possible buttons.
        :param default_opt: The default selected index from 0 to len - 1.
        :param width: The buttons' width.
        :param offset: The offset of the left edge
        :return: An array with the buttons created.
        """
        cmds.rowLayout(nc=3, p=layout, cat=(1, "left", offset))
        radio_collection = cmds.iconTextRadioCollection()
        buttons = []
        for opt in options:
            button = cmds.iconTextRadioButton(st='textOnly', l=opt, w=width, bgc=[0.4, 0.4, 0.4], h=20)
            buttons.append(button)
        cmds.iconTextRadioCollection(radio_collection, e=True, select=buttons[default_opt])
        return buttons

    @staticmethod
    def p4_exists(p4: P4, path: str) -> bool:
        """
        Checks whether the file already exists in the P4 file structure.
        :param p4: The connected P4 connection.
        :param path: The path of the file to check.
        :return: True if the file already exists on P4, otherwise False.
        """
        try:
            p4.run("files", path)
            return True
        except P4Exception:
            return False

    @staticmethod
    def p4_in_workspace(p4, path):
        """
        Checks whether a directory path is part of the P4 file structure.
        :param p4: The connected P4 connection.
        :param path: The path of the directory to check.
        :return: True if the directory is part of the P4 file structure, otherwise False.
        """
        try:
            p4.run("where", path)
            return True
        except P4Exception:
            return False

    def __intercept_save(self, ret_code):
        """
        Function to run when intercepting saving. Will check the file based on the specified parameters and add or check
        out a file as necessary. Can cancel saving.
        :param ret_code: The return code variable necessary for canceling saving.
        """
        continue_save = True

        # Only check if connected.
        if self._handler.is_connected():
            # Set up for custom cancellation error.
            string_key = "s_TfileIOStrings.rFileOpCancelledByUser"
            string_default = "File operation cancelled by user supplied callback."
            string_error = "Saving Canceled for Unknown Reasons."

            try:
                # Set up the P4 connection.
                self._handler.p4_connect()
                p4 = self._handler.p4

                check = True
                # Check whether the file is saved inside a P4 workspace if necessary.
                if not self.__options.get("outside_p4"):
                    path = os.path.dirname(cmds.file(q=True, sn=True))
                    check = self.p4_in_workspace(p4, path)

                # Executes the checks.
                if check and self.__state is not CustomSave.CheckType.NONE:
                    state = MessageType.ERROR if self.__state == CustomSave.CheckType.ERROR else MessageType.WARNING
                    checks_passed, warnings = self.__check_open_file()

                    # If the checks failed, propagate to the user as specified.
                    if not checks_passed:
                        for w in warnings:
                            self._send_to_log(w, state)

                        # Cancel saving if set to Error out.
                        if self.__state is CustomSave.CheckType.ERROR:
                            self._handler.p4_release()
                            string_error = f"{len(warnings)} Checks failed. See the log for more information. " \
                                           f"Saving Canceled."
                            cmds.displayString(string_key, replace=True, value=string_error)
                            Om.MScriptUtil.setBool(ret_code, False)
                            return

                # Add or check out the file from P4.
                file = cmds.file(q=True, sn=True)
                dir_name = os.path.dirname(file)
                if self.p4_in_workspace(p4, dir_name):
                    if not self.p4_exists(p4, file):
                        p4.run("add", file)
                    else:
                        p4.run("edit", file)
                self._handler.p4_release()

            except P4Exception as inst:
                self._handler.p4_release()

                # Handle P4Exception by canceling saving and informing the user.
                message = inst.errors
                if message == "":
                    message = inst.warnings
                self._handler.send_to_log(message, MessageType.ERROR)
                string_error = f"Saving canceled. \n {message}"
                continue_save = False

            # Set up the error message displayed.
            message = string_error if not continue_save else string_default
            cmds.displayString(string_key, replace=True, value=message)

        Om.MScriptUtil.setBool(ret_code, continue_save)

    def __check_open_file(self) -> (bool, [str]):
        """
        Checks the open Maya file on errors.
        :return: A tuple containing a boolean indicating whether the checks were passed successfully and an array
            containing possible error messages.
        """
        # Check the file path name.
        path = cmds.file(q=True, sn=True)
        success, warnings = self.__check_path(path)

        # If the file is not empty, also check the geometry.
        if cmds.ls(type="mesh"):
            success_geo, warnings_geo = self.__check_geometry()
            success = success_geo and success
            warnings = warnings_geo + warnings

        return success, warnings

    def __check_path(self, path) -> (bool, [str]):
        """
        Checks the given path on breaking conventions.
        :param path: The path to be checked.
        :return: A tuple containing a boolean indicating whether the checks were passed successfully and an array
            containing possible error messages.
        """
        success = True
        warning = []

        # Check the naming convention of the file.
        if self.__options.get("check_naming"):
            if self.__options.get("naming_approach") == 1:
                pattern = self.__options.get("naming_convention_regex")
            else:
                pattern = self.__options.get("naming_convention_prefix") + ".*" \
                          + self.__options.get("naming_convention_suffix")

            filename = os.path.basename(path)
            if not re.match(pattern, filename):
                warning.append(f"The naming convention with pattern {self.__options.get('naming_convention')} "
                               f"is not being respected.")
                success = False

        # Check the directory convention.
        if self.__options.get("check_directory"):
            path = os.path.realpath(path)
            if self.__options.get("directory"):
                directory = os.path.realpath(self.__options.get("directory"))
                if not os.path.commonprefix([path, directory]) == directory:
                    warning.append(f"The file should be saved in {directory}, but was saved in "
                                   f"{os.path.dirname(path)}.")
                    success = False

        return success, warning

    def __check_geometry(self) -> (bool, [str]):
        """
        Checks the current file on mistakes.
        :return: A tuple containing a boolean indicating whether the checks were passed successfully and an array
            containing possible error messages.
        """
        success = True
        warning = []

        # Check for non-manifold geometry.
        if self.__options.get("non_manifold"):
            objects = cmds.ls(type="mesh", dag=True)
            cmds.select(objects)
            non_manifold = mel.eval(r'polyCleanupArgList 4 { "1","2","1","0","0","0","0","0","0","1e-05","0","1e-05",'
                                    r'"0","1e-05","0","1","0","0" }')
            if non_manifold:
                success = False
                warning.append("Non-manifold geometry was found. Please clean up the geometry before saving.")

        # Check for ngons.
        if self.__options.get("ngons"):
            ngons = mel.eval(r'polyCleanupArgList 4 { "1","2","1","0","1","0","0","0","0","1e-05","0","1e-05","0",'
                             r'"1e-05","0","0","0","0" }')
            if ngons:
                success = False
                warning.append("Ngons were found. Please clean up the geometry before saving.")

        # Check for concave faces.
        if self.__options.get("concave"):
            concave = mel.eval(r'polyCleanupArgList 4 { "1","2","1","0","0","1","0","0","0","1e-05","0","1e-05","0",'
                               r'"1e-05","0","0","0","0" }')
            if concave:
                success = False
                warning.append("Concave faces were found. Please clean up the geometry before saving.")

        # Check for frozen transforms.
        if self.__options.get("frozen_transform"):
            objects = cmds.ls(type="mesh", dag=True)
            transforms = cmds.listRelatives(objects, parent=True, fullPath=True)
            for t in transforms:
                matrix = cmds.xform(t, q=True, matrix=True)
                om_matrix = Api_Om.MMatrix(matrix)

                if Api_Om.MMatrix() != om_matrix:
                    success = False
                    warning.append("Not all transforms were frozen.")
                    break

        # Check whether the objects are placed around the center.
        if self.__options.get("centered"):
            objects = cmds.ls(type="mesh", dag=True)
            for obj in objects:
                bbox = cmds.exactWorldBoundingBox(obj)
                x_zero_centered = bbox[0] < 1 and bbox[3] > -1
                y_zero_centered = bbox[1] < 1 and bbox[4] > -1
                z_zero_centered = bbox[2] < 1 and bbox[5] > -1

                if not (x_zero_centered and y_zero_centered and z_zero_centered):
                    success = False
                    warning.append("The meshes are not positioned around (0, 0, 0).")

        mel.eval('print "Result: Checked File\\n"')

        return success, warning

    def __create_callbacks(self):
        """
        Create a callback to intercept and possibly cancel saving.
        """
        self.__cb_id = Om.MSceneMessage.addCheckCallback(Om.MSceneMessage.kBeforeSaveCheck,
                                                         lambda ret_code, client_data: self.__intercept_save(ret_code))

    def get_pretty_name(self):
        return "Saving Criteria"


############################################################################################################
# ############################################ DOCKABLE BAR ############################################## #
############################################################################################################

# TODO: Open the actual settings window when pressing buttons
class P4Bar(object):
    """
    A bar displaying the current status of the P4 For Maya tool as well as keeping a log of all messages passed through.
    """
    __BAR_NAME = "P4ForMaya"                # The name of the docked control.
    __WINDOW_NAME = "P4ForMaya_Window"      # The name of the window of the docked control.

    def __init__(self):
        """
        Initialises a new bar.
        """
        self.__handler = None                       # Sets the handler to be able to open the window.
        self.__docked_window = self.__BAR_NAME      # The docked window.
        self.__log_window = ""                      # The window to log all messages in.
        self.__ui = ""                              # The UI of the docked window.

        self.__connected_icon = ""                  # The iconTextButton displaying the connection icon.
        self.__connected_text = ""                  # The text indicating whether the tool is connected.
        self.__log = []                             # An array containing all previously logged messages.
        self.__log_field = ""                       # The text field displaying the last logged message.
        self.__log_display = ""                     # The scroll field within the log window displaying all messages.

        # Create the actual UI.
        self.__create_ui()
        self.__create_log_window()

    def set_handler(self, handler):
        """
        Sets the handler to the specified handler.
        :param handler: The P4MayaControl object to be used.
        """
        self.__handler = handler
        cmds.iconTextButton(self.__connected_icon, e=True, c=self.__handler.open_window)

    def set_connected(self, connected: bool):
        """
        Changes the P4 connection display to the specified boolean.
        :param connected: A boolean indicating whether the tool is connected to P4.
        """
        if connected:
            cmds.iconTextButton(self.__connected_icon, e=True, i="confirm.png")
            cmds.text(self.__connected_text, e=True, l="Connected")
        else:
            cmds.iconTextButton(self.__connected_icon, e=True, i="SP_MessageBoxCritical.png")
            cmds.text(self.__connected_text, e=True, l="Not Connected")

    def add_to_log(self, log_message: str, msg_type: MessageType):
        """
        Adds a message to the log of the specified MessageType.
        :param log_message: The message to be logged.
        :param msg_type: The MessageType of the message.
        """
        cmds.textField(self.__log_field, e=True, text=log_message)
        colours = [[0.17, 0.17, 0.17], [0.88, 0.70, 0.30], [1, 0.48, 0.48]]
        cmds.textField(self.__log_field, e=True, bgc=colours[msg_type.value])

        self.__update_log(log_message, msg_type)

    def manage_callbacks(self, cb_id):
        """
        Manage callbacks. Currently, can only handle one at a time.
        :param cb_id: The ID of the callback to be handled.
        """
        cmds.dockControl(self.__docked_control, e=True, cc=lambda: Om.MSceneMessage.removeCallback(cb_id))

    def __create_ui(self):
        """
        Creates the docked bar.
        """

        # Remove remains of old instance.
        if cmds.dockControl(self.__BAR_NAME, q=True, ex=True):
            cmds.deleteUI(self.__BAR_NAME)
        if cmds.window(self.__WINDOW_NAME, q=True, ex=True):
            cmds.deleteUI(self.__WINDOW_NAME)

        # Create the window and overarching layout.
        self.__docked_window = cmds.window(self.__WINDOW_NAME, title="P4 For Maya")
        self.__ui = cmds.formLayout()

        self.__docked_control = cmds.dockControl(self.__BAR_NAME, content=self.__docked_window, a="bottom",
                                                 allowedArea=["bottom", "top"], l="P4 For Maya", ret=False)

        # Create the right-click menu.
        connected = cmds.rowLayout(nc=2)
        cmds.popupMenu(b=3)
        cmds.menuItem(l="Change Connection", c=lambda _: self.__handler.open_tab(0))
        cmds.menuItem(d=True)
        cmds.menuItem(l="File History",  c=lambda _: self.__handler.open_tab(1))
        cmds.menuItem(l="Saving Criteria", c=lambda _: self.__handler.open_tab(2))
        cmds.menuItem(l="Submit", c=lambda _: self.__handler.open_tab(3))

        # Create the connection display.
        self.__connected_icon = cmds.iconTextButton(style="iconOnly", i="confirm.png", h=18, w=18,)
        self.__connected_text = cmds.text(l="Connected")

        # Create the log display.
        log = cmds.rowLayout(nc=3, p=self.__ui)
        cmds.text(l="P4:", w=50)
        self.__log_field = cmds.textField(ed=False, w=750, font="smallPlainLabelFont", bgc=[0.17, 0.17, 0.17])
        cmds.iconTextButton(style="iconOnly", i="futurePulldownIcon.png", h=17, w=17,
                            c=self.__show_full_log)

        cmds.formLayout(self.__ui, e=True, af={(log, "left", 0), (connected, "right", 10)})

    # TODO: Make it scaleable/Copyable/whatever :P
    def __create_log_window(self):
        """
        Creates the window containing all log messages.
        """
        self.__log_window = cmds.window(w=400, h=500, title="P4 Log", ret=True)
        cmds.columnLayout(adj=True)
        self.__log_display = cmds.scrollField(h=500, wordWrap=True, ed=False)
        self.add_to_log("P4 For Maya started", MessageType.LOG)

    def __update_log(self, log_message, msg_type):
        """
        Updates the log with the new message and message type.
        :param log_message: The message to log.
        :param msg_type: The MessageType of the logged message.
        """
        self.__log.append(f">> [{msg_type.name}] " + log_message)
        if len(self.__log) > 50:
            self.__log.remove(0)
        log = "\n\n".join(self.__log)
        cmds.scrollField(self.__log_display, e=True, text=log)

    def __show_full_log(self):
        """
        Shows the log window.
        """
        cmds.showWindow(self.__log_window)


############################################################################################################
# ############################################# CONTROLLERS ############################################## #
############################################################################################################

class P4MayaControl:
    """
    Base class of P4 for Maya. Mediator between the modules and the bar and handles the P4 connection.
    """
    def __init__(self, window: str, layout: str, tab_layout: str, bar: P4Bar):
        """
        Initialises a new P4MayaControl object.
        :param window: The window containing the settings and actions of the tool.
        :param layout: The main layout of the window to add the connected display to.
        :param tab_layout: The tab layout of the window
        :param bar: The bar object connected to the tool.
        """
        self.p4 = P4()              # The P4 instance used throughout the application.
        self.window = window        # The window with the settings and actions of the tool.
        self.__bar = bar            # The bar docked in Maya showing the current state and log.
        self.__connect = None       # The connection module to log connection issues in.
        self.__connected = False    # Whether the tool is connected to P4.
        self.__callbacks = []       # The callbacks managed.
        self.__layout_settings = tab_layout

        # Attach visibility of connection to the settings window.
        row = cmds.rowLayout(p=layout, nc=2)
        self.__connected_icon = cmds.iconTextButton(style="iconOnly", i="confirm.png", h=18, w=18, )
        self.__connected_text = cmds.text(l="Connected")
        cmds.formLayout(layout, e=True, af={(row, "bottom", 10), (row, "right", 10)})

    def open_window(self):
        """
        Opens the settings and action window.
        """
        cmds.showWindow(self.window)

    def open_tab(self, index):
        """
        Opens the settings window on the specified tab.
        """
        cmds.showWindow(self.window)
        cmds.tabLayout(self.__layout_settings, e=True, sti=index+1)

    # TODO: Maybe at some point this will be properly managed
    def manage_callback(self, cb_id):
        """
        Adds the callback to be managed. (Currently, can only handle one.)
        :param cb_id: The ID from callback to be managed.
        """
        self.__callbacks.append(cb_id)
        self.__bar.manage_callbacks(cb_id)

    def change_connection(self, port: str, user: str, client: str, connected: bool):
        """
        Changes the connection of the tool to the given settings. Will disconnect if still connected.
        :param port: The new port.
        :param user: The new user.
        :param client: The new workspace.
        :param connected: Whether the tool is connected to P4.
        """
        self.p4_release()
        if connected:
            self.p4.port = port
            self.p4.user = user
            self.p4.client = client

        self.__set_connected(connected)

    def send_to_log(self, log_message, msg_type):
        """
        Sends the given message to be logged.
        :param log_message: The message to be logged.
        :param msg_type: The MessageType of the message.
        """
        self.__bar.add_to_log(log_message, msg_type)

    def is_connected(self) -> bool:
        """
        Checks whether the tool is connected to P4.
        :return: Boolean indicating whether the tool is connected.
        """
        return self.__connected

    def __set_connected(self, connected: bool):
        """
        Sets the display of connection to the state specified.
        :param connected: Boolean indicating whether the tool is connected.
        """
        # Set own display
        if connected:
            cmds.iconTextButton(self.__connected_icon, e=True, i="confirm.png")
            cmds.text(self.__connected_text, e=True, l="Connected")
        else:
            cmds.iconTextButton(self.__connected_icon, e=True, i="SP_MessageBoxCritical.png")
            cmds.text(self.__connected_text, e=True, l="Not Connected")

        # Set the bar's display
        self.__bar.set_connected(connected)
        self.__connected = connected

    def p4_connect(self, handle_error: bool = True):
        """
        Connects to P4 and logs errors as necessary. Always use in conjunction with release.
        """
        try:
            self.p4.connect()
            self.p4.run("login", "-s")

        except P4Exception as inst:
            self.p4_release()
            if handle_error:
                log_msg = "\n".join(inst.errors)
                if log_msg == "":
                    log_msg = "The server given does not exist. Please try again."
                self.send_to_log(log_msg, MessageType.ERROR)
                self.__connect.log_connection(log_msg)
            else:
                raise inst

    def p4_release(self):
        """
        Disconnects the P4 connection if it was connected.
        """
        try:
            if self.p4.connected():
                self.p4.disconnect()
        except P4Exception:
            # Was not connected
            pass


class PreferenceHandler:
    """
    The preference handler of the P4 For Maya tool. It saves and loads preferences.
    """
    __PREF_FILE_NAME = "P4ForMaya_Preferences.json"         # The file name of the preference file.
    __OPTION_VAR_NAME = "P4ForMaya_Preferences_Location"    # The option variable name of the Maya variable.

    def __init__(self):
        """
        Initialises a Preference Handler.
        """
        self.__pref_file = ""       # The preference file's path
        self.__preferences = {}     # A dictionary containing all the preferences
        self.__load_pref()

    def get_pref(self, class_key: str, var_key: str):
        """
        Gets the preferences for a specific variable of a specific class.
        :param class_key: The key indicating the class to which the variable belongs.
        :param var_key: The key indicating the variable to be gotten.
        :return: The saved value of the variable.
        """
        class_prefs = self.__preferences.get(class_key, {})
        return class_prefs.get(var_key, None)

    def set_pref(self, class_key, var_key, value):
        """
        Sets the preferences of the indicated variable of the specified class to the given value.
        :param class_key: The key indicating the class to which the variable belongs.
        :param var_key: The key indicating the variable to be set.
        :param value: The value to which the variable should be set. Has to be JSON serializable.
        """
        class_prefs = self.__preferences.get(class_key, {})
        class_prefs.update({var_key: value})
        self.__preferences.update({class_key: class_prefs})

    def save_pref(self):
        """
        Saves the preferences to the preference file.
        """
        path = cmds.internalVar(upd=True)
        file = os.path.join(path, self.__PREF_FILE_NAME)
        with open(file, "w") as f:
            f.write(json.dumps(self.__preferences))

        # Create a variable for the file location to find it back upon restart.
        cmds.optionVar(sv=(self.__OPTION_VAR_NAME, file))

    def __load_pref(self):
        """
        Loads the preferences into the preference handler.
        """
        if cmds.optionVar(ex=self.__OPTION_VAR_NAME):
            path = cmds.optionVar(q=self.__OPTION_VAR_NAME)

            # if found, then load in the preferences saved.
            if os.path.exists(path):
                with open(path, "r") as f:
                    self.__preferences = json.loads(f.readline())


class P4MayaFactory:
    """
    Creates the P4 For Maya Application.
    """
    def __init__(self):
        """
        Create a new P4 For Maya setup.
        """
        window, layout, tabs, modules = self.__create_window()
        bar = P4Bar()
        controller = P4MayaControl(window, layout, tabs, bar)
        bar.set_handler(controller)
        self.window = window

        for m in modules:
            m.set_handler(controller)

    @staticmethod
    def __create_modules(tabs_layout: str) -> (PreferenceHandler, [P4MayaModule]):
        """
        Creates the modules of the tool and attaches their UI to the given layout.
        :param tabs_layout: The layout to which the modules should be attached.
        :return: A tuple containing the created Preference Handler and an array of the Maya Modules created.
        """
        pref_handler = PreferenceHandler()
        connector = Connector(pref_handler, tabs_layout)
        checks = CustomSave(pref_handler, tabs_layout)
        changelog = ChangeLog(tabs_layout)
        rollback = Rollback(tabs_layout)

        return pref_handler, (connector, changelog, rollback, checks)

    @classmethod
    def __create_window(cls) -> (str, str, [P4MayaModule]):
        """
        Creates the settings window of the tool.
        :return: A tuple containing the window, the overarching layout and a list of the created Maya Modules.
        """
        # Create the window and its main layout.
        # window = cmds.window("P4MayaWindow", l="P4 Settings and Actions")
        window = cmds.window(title="P4 Settings and Actions", width=350, height=500, ret=True)
        master_layout = cmds.formLayout(w=350)
        tabs_layout = cmds.tabLayout(p=master_layout)
        cmds.formLayout(master_layout, e=True, af=[(tabs_layout, "top", 0),
                                                   (tabs_layout, "right", 0),
                                                   (tabs_layout, "left", 0)])

        # Create the modules and set the tab names.
        pref_handler, modules = cls.__create_modules(tabs_layout)
        for m in modules:
            ui = m.get_ui()
            cmds.tabLayout(tabs_layout, e=True, tabLabel=(ui, m.get_pretty_name()))

        cmds.window(window, e=True, cc=pref_handler.save_pref)
        cmds.tabLayout(tabs_layout, e=True, mt=[4, 2])
        return window, master_layout, tabs_layout, modules


factory = P4MayaFactory()
