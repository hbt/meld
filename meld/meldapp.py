### Copyright (C) 2002-2006 Stephen Kennedy <stevek@gnome.org>

### This program is free software; you can redistribute it and/or modify
### it under the terms of the GNU General Public License as published by
### the Free Software Foundation; either version 2 of the License, or
### (at your option) any later version.

### This program is distributed in the hope that it will be useful,
### but WITHOUT ANY WARRANTY; without even the implied warranty of
### MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
### GNU General Public License for more details.

### You should have received a copy of the GNU General Public License
### along with this program; if not, write to the Free Software
### Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

# system
import sys
import os
import optparse
from gettext import gettext as _

# gtk
import gtk
import gtk.glade
import gobject

# Drag'N'Drop support needs gnomevfs
try:
    import gnomevfs
    gnomevfs_available = True
except ImportError:
    gnomevfs_available = False

# project
import paths
from ui import gnomeglade
import misc
from ui import notebooklabel
import filediff
import filemerge
import vcview
import dirdiff
import preferences
import task
import vc

from util.sourceviewer import srcviewer

version = "1.4.0"

################################################################################
#
# NewDocDialog
#
################################################################################

class NewDocDialog(gnomeglade.Component):
    def __init__(self, parentapp):
        gnomeglade.Component.__init__(self, paths.ui_dir("meldapp.glade"), "newdialog")
        self.map_widgets_into_lists(["fileentry", "direntry", "vcentry", "three_way_compare"])
        self.entrylists = self.fileentry, self.direntry, self.vcentry
        self.widget.set_transient_for(parentapp.widget)
        self.fileentry[0].set_sensitive(self.three_way_compare[0].get_active())
        self.direntry[0].set_sensitive(self.three_way_compare[1].get_active())
        self.diff_methods = (parentapp.append_filediff,
                             parentapp.append_dirdiff,
                             parentapp.append_vcview)
        self.widget.show_all()

    def on_entry_activate(self, entry):
        for el in self.entrylists:
            if entry in el:
                i = el.index(entry)
                if i == len(el) - 1:
                    self.button_ok.grab_focus()
                else:
                    el[i+1].focus_entry()

    def on_three_way_toggled(self, button):
        page = self.three_way_compare.index(button)
        self.entrylists[page][0].set_sensitive( button.get_active() )
        self.entrylists[page][not button.get_active()].focus_entry()

    def on_response(self, dialog, arg):
        if arg == gtk.RESPONSE_OK:
            page = self.notebook.get_current_page()
            paths = [e.get_full_path() or "" for e in self.entrylists[page]]
            if page < 2 and not self.three_way_compare[page].get_active():
                paths.pop(0)
            for path in paths:
                self.entrylists[page][0].prepend_history(path)
            self.diff_methods[page](paths)
        self.widget.destroy()


################################################################################
#
# MeldStatusBar
#
################################################################################

class MeldStatusBar(object):

    def __init__(self, task_progress, task_status, doc_status):
        self.task_progress = task_progress
        self.task_status = task_status
        self.doc_status = doc_status

    def set_task_status(self, status):
        self.task_status.pop(1)
        self.task_status.push(1, status)

    def set_doc_status(self, status):
        self.doc_status.pop(1)
        self.doc_status.push(1, status)


################################################################################
#
# MeldApp
#
################################################################################

class MeldApp(gnomeglade.Component):

    #
    # init
    #
    def __init__(self):
        gladefile = paths.ui_dir("meldapp.glade")
        gtk.window_set_default_icon_name("icon")
        if getattr(gobject, "pygobject_version", ()) >= (2, 16, 0):
            gobject.set_application_name("Meld")
        gnomeglade.Component.__init__(self, gladefile, "meldapp")
        self.prefs = preferences.MeldPreferences()

        actions = (
            ("FileMenu", None, _("_File")),
            ("New",     gtk.STOCK_NEW,      _("_New..."), "<control>N", _("Start a new comparison"), self.on_menu_file_new_activate),
            ("Save",    gtk.STOCK_SAVE,     None, None, _("Save the current file"), self.on_menu_save_activate),
            ("SaveAs",  gtk.STOCK_SAVE_AS,  None, "<control><shift>S", "Save the current file with a different name", self.on_menu_save_as_activate),
            ("Close",   gtk.STOCK_CLOSE,    None, None, _("Close the current file"), self.on_menu_close_activate),
            ("Quit",    gtk.STOCK_QUIT,     None, None, _("Quit the program"), self.on_menu_quit_activate),

            ("EditMenu", None, _("_Edit")),
            ("Undo",    gtk.STOCK_UNDO,     None, "<control>Z", _("Undo the last action"), self.on_menu_undo_activate),
            ("Redo",    gtk.STOCK_REDO,     None, "<control><shift>Z", _("Redo the last undone action"), self.on_menu_redo_activate),
            ("Cut",     gtk.STOCK_CUT,      None, None, _("Cut the selection"), self.on_menu_cut_activate),
            ("Copy",    gtk.STOCK_COPY,     None, None, _("Copy the selection"), self.on_menu_copy_activate),
            ("Paste",   gtk.STOCK_PASTE,    None, None, _("Paste the clipboard"), self.on_menu_paste_activate),
            ("Find",    gtk.STOCK_FIND,     None, None, _("Search for text"), self.on_menu_find_activate),
            ("FindNext", None,              _("Find Ne_xt"), "<control>G", _("Search forwards for the same text"), self.on_menu_find_next_activate),
            ("Replace", gtk.STOCK_FIND_AND_REPLACE, _("_Replace"), "<control>H", _("Find and replace text"), self.on_menu_replace_activate),
            ("Preferences", gtk.STOCK_PREFERENCES, _("Prefere_nces"), None, _("Configure the application"), self.on_menu_preferences_activate),

            ("ChangesMenu", None, _("_Changes")),
            ("NextChange", gtk.STOCK_GO_DOWN, _("Next change"), "<control>D", _("Go to the next change"), self.on_menu_edit_down_activate),
            ("PrevChange", gtk.STOCK_GO_UP,   _("Previous change"), "<control>E", _("Go to the previous change"), self.on_menu_edit_up_activate),

            ("ViewMenu", None, _("_View")),
            ("FileStatus",  None, _("File status")),
            ("VcStatus",    None, _("Version status")),
            ("FileFilters",  None, _("File filters")),
            ("Stop",    gtk.STOCK_STOP,     None, "Escape", _("Stop the current action"), self.on_toolbar_stop_clicked),
            ("Refresh", gtk.STOCK_REFRESH,  None, "<control>R", _("Refresh the view"), self.on_menu_refresh_activate),
            ("Reload",  gtk.STOCK_REFRESH,  _("Reload"), "<control><shift>R", _("Reload the comparison"), self.on_menu_reload_activate),

            ("HelpMenu", None, _("_Help")),
            ("Help",        gtk.STOCK_HELP,  _("_Contents"), "F1", _("Open the Meld manual"), self.on_menu_help_activate),
            ("BugReport",   gtk.STOCK_DIALOG_WARNING, _("Report _Bug"), None, _("Report a bug in Meld"), self.on_menu_help_bug_activate),
            ("About",       gtk.STOCK_ABOUT, None, None, _("About this program"), self.on_menu_about_activate),
        )
        toggleactions = (
            ("Fullscreen",       None, _("Full Screen"), "F11", _("View the comparison in full screen"), self.on_action_fullscreen_toggled, False),
            ("ToolbarVisible",   None, _("_Toolbar"),   None, _("Show or hide the toolbar"),   self.on_menu_toolbar_toggled,   self.prefs.toolbar_visible),
            ("StatusbarVisible", None, _("_Statusbar"), None, _("Show or hide the statusbar"), self.on_menu_statusbar_toggled, self.prefs.statusbar_visible)
        )
        ui_file = paths.ui_dir("meldapp-ui.xml")
        self.actiongroup = gtk.ActionGroup('MainActions')
        self.actiongroup.set_translation_domain("meld")
        self.actiongroup.add_actions(actions)
        self.actiongroup.add_toggle_actions(toggleactions)
        self.ui = gtk.UIManager()
        self.ui.insert_action_group(self.actiongroup, 0)
        self.ui.add_ui_from_file(ui_file)
        self.ui.connect("connect-proxy", self._on_uimanager_connect_proxy)
        self.ui.connect("disconnect-proxy", self._on_uimanager_disconnect_proxy)

        for menuitem in ("Save", "Undo"):
            self.actiongroup.get_action(menuitem).props.is_important = True
        self.widget.add_accel_group(self.ui.get_accel_group())
        self.menubar = self.ui.get_widget('/Menubar')
        self.toolbar = self.ui.get_widget('/Toolbar')
        self.appvbox.pack_start(self.menubar, expand=False)
        self.appvbox.pack_start(self.toolbar, expand=False)
        # TODO: should possibly use something other than doc_status
        self._menu_context = self.doc_status.get_context_id("Tooltips")
        self.statusbar = MeldStatusBar(self.task_progress, self.task_status, self.doc_status)
        self.widget.drag_dest_set(
            gtk.DEST_DEFAULT_MOTION | gtk.DEST_DEFAULT_HIGHLIGHT | gtk.DEST_DEFAULT_DROP,
            [ ('text/uri-list', 0, 0) ],
            gtk.gdk.ACTION_COPY)
        if gnomevfs_available:
            self.widget.connect('drag_data_received', self.on_widget_drag_data_received)
        self.toolbar.set_style( self.prefs.get_toolbar_style() )
        self.toolbar.props.visible = self.prefs.toolbar_visible
        self.status_box.props.visible = self.prefs.statusbar_visible
        self.prefs.notify_add(self.on_preference_changed)
        self.idle_hooked = 0
        self.scheduler = task.LifoScheduler()
        self.scheduler.connect("runnable", self.on_scheduler_runnable )
        self.widget.set_default_size(self.prefs.window_size_x, self.prefs.window_size_y)
        self.ui.ensure_update()
        self.widget.show()
        self.diff_handler = None
        self.widget.connect('focus_in_event', self.on_focus_change)
        self.widget.connect('focus_out_event', self.on_focus_change)

    def on_focus_change(self, widget, event, callback_data = None):
        for idx in range(self.notebook.get_n_pages()):
            w = self.notebook.get_nth_page(idx)
            if hasattr(w.get_data("pyobject"), 'on_focus_change'):
                w.get_data("pyobject").on_focus_change()
        # Let the rest of the stack know about this event
        return False

    def on_widget_drag_data_received(self, wid, context, x, y, selection_data, info, time):
        if len(selection_data.get_uris()) != 0:
            paths = [gnomevfs.get_local_path_from_uri(u) for u in selection_data.get_uris()]
            self.open_paths(paths)
            return True

    def _on_uimanager_connect_proxy(self, ui, action, widget):
        tooltip = action.props.tooltip
        if not tooltip:
            return
        if isinstance(widget, gtk.MenuItem):
            cid = widget.connect("select", self._on_action_item_select_enter, tooltip)
            cid2 = widget.connect("deselect", self._on_action_item_deselect_leave)
            widget.set_data("meldapp::proxy-signal-ids", (cid, cid2))
        elif isinstance(widget, gtk.ToolButton):
            cid = widget.child.connect("enter", self._on_action_item_select_enter, tooltip)
            cid2 = widget.child.connect("leave", self._on_action_item_deselect_leave)
            widget.set_data("meldapp::proxy-signal-ids", (cid, cid2))

    def _on_uimanager_disconnect_proxy(self, ui, action, widget):
        cids = widget.get_data("meldapp::proxy-signal-ids")
        if not cids:
            return
        if isinstance(widget, gtk.ToolButton):
            widget = widget.child
        for cid in cids:
            widget.disconnect(cid)

    def _on_action_item_select_enter(self, item, tooltip):
        self.statusbar.doc_status.push(self._menu_context, tooltip)

    def _on_action_item_deselect_leave(self, item):
        self.statusbar.doc_status.pop(self._menu_context)

    def on_idle(self):
        ret = self.scheduler.iteration()
        if ret:
            if type(ret) in (type(""), type(u"")):
                self.statusbar.set_task_status(ret)
            elif type(ret) == type(0.0):
                self.statusbar.task_progress.set_fraction(ret)
            else:
                self.statusbar.task_progress.pulse()
        else:
            self.statusbar.task_progress.set_fraction(0)
        if self.scheduler.tasks_pending():
            self.actiongroup.get_action("Stop").set_sensitive(True)
            return 1
        else:
            self.statusbar.set_task_status("")
            self.idle_hooked = 0
            self.actiongroup.get_action("Stop").set_sensitive(False)
            return 0

    def on_scheduler_runnable(self, sched):
        if not self.idle_hooked:
            self.idle_hooked = 1
            gobject.idle_add( self.on_idle )

    def on_preference_changed(self, key, value):
        if key == "toolbar_style":
            self.toolbar.set_style( self.prefs.get_toolbar_style() )
        elif key == "statusbar_visible":
            self.status_box.props.visible = self.prefs.statusbar_visible
        elif key == "toolbar_visible":
            self.toolbar.props.visible = self.prefs.toolbar_visible

    #
    # General events and callbacks
    #
    def on_delete_event(self, *extra):
        return self.on_menu_quit_activate()

    def on_switch_page(self, notebook, page, which):
        newdoc = notebook.get_nth_page(which).get_data("pyobject")
        newseq = newdoc.undosequence
        oldidx = notebook.get_current_page()
        if oldidx >= 0:
            olddoc = notebook.get_nth_page(oldidx).get_data("pyobject")
            olddoc.disconnect(self.diff_handler)
            olddoc.on_container_switch_out_event(self.ui)
        self.actiongroup.get_action("Undo").set_sensitive(newseq.can_undo())
        self.actiongroup.get_action("Redo").set_sensitive(newseq.can_redo())
        nbl = self.notebook.get_tab_label( newdoc.widget )
        self.widget.set_title(nbl.get_label_text() + " - Meld")
        self.statusbar.set_doc_status("")
        newdoc.on_container_switch_in_event(self.ui)
        self.diff_handler = newdoc.connect("next-diff-changed",
                                           self.on_next_diff_changed)
        self.scheduler.add_task( newdoc.scheduler )

    def on_notebook_label_changed(self, component, text):
        nbl = self.notebook.get_tab_label( component.widget )
        nbl.set_label_text(text)
        self.widget.set_title(text + " - Meld")
        self.notebook.child_set_property(component.widget, "menu-label", text)

    def on_can_undo(self, undosequence, can):
        self.actiongroup.get_action("Undo").set_sensitive(can)

    def on_can_redo(self, undosequence, can):
        self.actiongroup.get_action("Redo").set_sensitive(can)

    def on_next_diff_changed(self, doc, have_prev, have_next):
        self.actiongroup.get_action("PrevChange").set_sensitive(have_prev)
        self.actiongroup.get_action("NextChange").set_sensitive(have_next)

    def on_size_allocate(self, window, rect):
        self.prefs.window_size_x = rect.width
        self.prefs.window_size_y = rect.height

    #
    # Toolbar and menu items (file)
    #
    def on_menu_file_new_activate(self, menuitem):
        NewDocDialog(self)

    def on_menu_save_activate(self, menuitem):
        self.current_doc().save()

    def on_menu_save_as_activate(self, menuitem):
        self.current_doc().save_as()

    def on_menu_close_activate(self, *extra):
        i = self.notebook.get_current_page()
        if i >= 0:
            page = self.notebook.get_nth_page(i).get_data("pyobject")
            self.try_remove_page(page)

    def on_menu_quit_activate(self, *extra):
        # Delete pages from right-to-left.  This ensures that if a version
        # control page is open in the far left page, it will be closed last.
        for c in reversed(self.notebook.get_children()):
            page = c.get_data("pyobject")
            self.notebook.set_current_page(self.notebook.page_num(page.widget))
            response = self.try_remove_page(page, appquit=1)
            if response == gtk.RESPONSE_CANCEL:
                return gtk.RESPONSE_CANCEL
        for c in self.notebook.get_children():
            c.get_data("pyobject").on_quit_event()
        gtk.main_quit()
        return gtk.RESPONSE_CLOSE

    #
    # Toolbar and menu items (edit)
    #
    def on_menu_undo_activate(self, *extra):
        self.current_doc().on_undo_activate()

    def on_menu_redo_activate(self, *extra):
        self.current_doc().on_redo_activate()

    def on_menu_refresh_activate(self, *extra):
        self.current_doc().on_refresh_activate()

    def on_menu_reload_activate(self, *extra):
        self.current_doc().on_reload_activate()
  
    def on_menu_find_activate(self, *extra):
        self.current_doc().on_find_activate()

    def on_menu_find_next_activate(self, *extra):
        self.current_doc().on_find_next_activate()

    def on_menu_replace_activate(self, *extra):
        self.current_doc().on_replace_activate()

    def on_menu_copy_activate(self, *extra):
        widget = self.widget.get_focus()
        if isinstance(widget, gtk.Editable):
            widget.copy_clipboard()
        elif isinstance(widget, gtk.TextView):
            widget.emit("copy-clipboard")

    def on_menu_cut_activate(self, *extra):
        widget = self.widget.get_focus()
        if isinstance(widget, gtk.Editable):
            widget.cut_clipboard()
        elif isinstance(widget, gtk.TextView):
            widget.emit("cut-clipboard")

    def on_menu_paste_activate(self, *extra):
        widget = self.widget.get_focus()
        if isinstance(widget, gtk.Editable):
            widget.paste_clipboard()
        elif isinstance(widget, gtk.TextView):
            widget.emit("paste-clipboard")

    #
    # Toolbar and menu items (settings)
    #
    def on_menu_preferences_activate(self, item):
        preferences.PreferencesDialog(self)

    def on_action_fullscreen_toggled(self, widget):
        is_full = self.widget.window.get_state() & gtk.gdk.WINDOW_STATE_FULLSCREEN
        if widget.get_active() and not is_full:
            self.widget.fullscreen()
        elif is_full:
            self.widget.unfullscreen()

    def on_menu_toolbar_toggled(self, widget):
        self.prefs.toolbar_visible = widget.get_active()

    def on_menu_statusbar_toggled(self, widget):
        self.prefs.statusbar_visible = widget.get_active()

    #
    # Toolbar and menu items (help)
    #
    def on_menu_help_activate(self, button):
        misc.open_uri("ghelp:///"+os.path.abspath(paths.help_dir("C/meld.xml")))

    def on_menu_help_bug_activate(self, button):
        misc.open_uri("http://bugzilla.gnome.org/buglist.cgi?query=product%3Ameld")

    def on_menu_about_activate(self, *extra):
        gtk.about_dialog_set_url_hook(lambda dialog, uri: misc.open_uri(uri))
        about = gtk.glade.XML(paths.ui_dir("meldapp.glade"), "about").get_widget("about")
        about.props.version = version
        about.set_transient_for(self.widget)
        about.run()
        about.hide()

    #
    # Toolbar and menu items (misc)
    #
    def on_menu_edit_down_activate(self, *args):
        self.current_doc().next_diff(gtk.gdk.SCROLL_DOWN)

    def on_menu_edit_up_activate(self, *args):
        self.current_doc().next_diff(gtk.gdk.SCROLL_UP)

    def on_toolbar_stop_clicked(self, *args):
        self.current_doc().stop()

    def try_remove_page(self, page, appquit=0):
        "See if a page will allow itself to be removed"
        response = page.on_delete_event(appquit)
        if response != gtk.RESPONSE_CANCEL:
            self.scheduler.remove_scheduler( page.scheduler )
            i = self.notebook.page_num( page.widget )
            assert(i>=0)
            # If the page we're removing is the current page, we need to trigger a switch out
            if self.notebook.get_current_page() == i:
                page.on_container_switch_out_event(self.ui)
            self.notebook.remove_page(i)
            if self.notebook.get_n_pages() == 0:
                self.widget.set_title("Meld")
        return response

    def on_file_changed(self, srcpage, filename):
        for c in self.notebook.get_children():
            page = c.get_data("pyobject")
            if page != srcpage:
                page.on_file_changed(filename)

    def _append_page(self, page, icon):
        nbl = notebooklabel.NotebookLabel(icon, "", lambda b: self.try_remove_page(page))
        self.notebook.append_page( page.widget, nbl)
        self.notebook.set_current_page( self.notebook.page_num(page.widget) )
        self.scheduler.add_scheduler(page.scheduler)
        page.connect("label-changed", self.on_notebook_label_changed)
        page.connect("file-changed", self.on_file_changed)
        page.connect("create-diff", lambda obj,arg: self.append_diff(arg) )
        page.connect("status-changed", lambda junk,arg: self.statusbar.set_doc_status(arg) )

    def append_dirdiff(self, dirs, auto_compare=False):
        assert len(dirs) in (1,2,3)
        doc = dirdiff.DirDiff(self.prefs, len(dirs))
        self._append_page(doc, "tree-folder-normal")
        doc.set_locations(dirs)
        # FIXME: This doesn't work, as dirdiff behaves differently to vcview
        if auto_compare:
            doc.on_button_diff_clicked(None)
        return doc

    def append_filediff(self, files):
        assert len(files) in (1, 2, 3, 4)
        if len(files) == 4:
            doc = filemerge.FileMerge(self.prefs, 3)
        else:
            doc = filediff.FileDiff(self.prefs, len(files))
        seq = doc.undosequence
        seq.clear()
        seq.connect("can-undo", self.on_can_undo)
        seq.connect("can-redo", self.on_can_redo)
        self._append_page(doc, "tree-file-normal")
        doc.set_files(files)
        return doc

    def append_diff(self, paths, auto_compare=False):
        dirslist = [p for p in paths if os.path.isdir(p)]
        fileslist = [p for p in paths if os.path.isfile(p)]
        if dirslist and fileslist:
            # build new file list appending previous found filename to dirs (like diff)
            lastfilename = fileslist[0]
            builtfilelist = []
            for elem in paths:
                if os.path.isdir(elem):
                    builtfilename = os.path.join(elem, lastfilename)
                    if os.path.isfile(builtfilename):
                        elem = builtfilename
                    else:
                        # exit at first non found directory + file
                        misc.run_dialog(_("Cannot compare a mixture of files and directories.\n"),
                                          parent=self,
                                          buttonstype=gtk.BUTTONS_OK)
                        return
                else:
                     lastfilename = os.path.basename(elem)
                builtfilelist.append(elem)
            return self.append_filediff(builtfilelist)
        elif dirslist:
            return self.append_dirdiff(paths, auto_compare)
        else:
            return self.append_filediff(paths)

    def append_vcview(self, locations, auto_compare=False):
        assert len(locations) in (1,)
        location = locations[0]
        doc = vcview.VcView(self.prefs)
        self._append_page(doc, "vc-icon")
        doc.set_location(location)
        if auto_compare:
            doc.on_button_diff_clicked(None)
        return doc

    #
    # Current doc actions
    #
    def current_doc(self):
        "Get the current doc or a dummy object if there is no current"
        index = self.notebook.get_current_page()
        if index >= 0:
            return self.notebook.get_nth_page(index).get_data("pyobject")
        class DummyDoc(object):
            def __getattr__(self, a): return lambda *x: None
        return DummyDoc()

    #
    # Usage
    #
    def diff_files_callback(self, option, opt_str, value, parser):
        """Gather --diff arguments and append to a list"""
        assert value is None
        diff_files_args = []
        while parser.rargs:
            # Stop if we find a short- or long-form arg, or a '--'
            # Note that this doesn't handle negative numbers.
            arg = parser.rargs[0]
            if arg[:2] == "--" or (arg[:1] == "-" and len(arg) > 1):
                break
            else:
                diff_files_args.append(arg)
                del parser.rargs[0]

        if len(diff_files_args) not in (1, 2, 3, 4):
            raise optparse.OptionValueError(
                _("wrong number of arguments supplied to --diff"))
        parser.values.diff.append(diff_files_args)

    def parse_args(self, rawargs):
        usages = [("", _("Start with an empty window")),
                  ("<%s|%s>" % (_("file"), _("dir")), _("Start a version control comparison")),
                  ("<%s> <%s> [<%s>]" % ((_("file"),) * 3), _("Start a 2- or 3-way file comparison")),
                  ("<%s> <%s> [<%s>]" % ((_("dir"),) * 3), _("Start a 2- or 3-way directory comparison")),
                  ("<%s> <%s>" % (_("file"), _("dir")), _("Start a comparison between file and dir/file"))]
        pad_args_fmt = "%-" + str(max([len(s[0]) for s in usages])) + "s %s"
        usage = "\n" + "\n".join(["  %prog " + pad_args_fmt % u for u in usages])

        parser = optparse.OptionParser(
            usage=usage,
            description=_("Meld is a file and directory comparison tool."),
            version="%prog " + version)
        parser.add_option("-L", "--label", action="append", default=[],
            help=_("Set label to use instead of file name"))
        parser.add_option("-a", "--auto-compare", action="store_true", default=False,
            help=_("Automatically compare all differing files on startup"))
        parser.add_option("-u", "--unified", action="store_true", help=_("Ignored for compatibility"))
        parser.add_option("-c", "--context", action="store_true", help=_("Ignored for compatibility"))
        parser.add_option("-e", "--ed", action="store_true", help=_("Ignored for compatibility"))
        parser.add_option("-r", "--recursive", action="store_true", help=_("Ignored for compatibility"))
        parser.add_option("", "--diff", action="callback", callback=self.diff_files_callback,
                          dest="diff", default=[],
                          help=_("Creates a diff tab for up to 3 supplied files or directories."))
        options, args = parser.parse_args(rawargs)
        if len(args) > 4:
            parser.error(_("too many arguments (wanted 0-4, got %d)") % len(args))

        for files in options.diff:
            self.append_diff(files)

        tab = self.open_paths(args, options.auto_compare)
        if tab:
            tab.set_labels(options.label)

    def _single_file_open(self, path):
        doc = vcview.VcView(self.prefs)
        def cleanup():
            self.scheduler.remove_scheduler(doc.scheduler)
        self.scheduler.add_task(cleanup)
        self.scheduler.add_scheduler(doc.scheduler)
        doc.set_location(path)
        doc.connect("create-diff", lambda obj,arg: self.append_diff(arg))
        doc.run_diff([path])

    def open_paths(self, paths, auto_compare=False):
        tab = None
        if len(paths) == 1:
            a = paths[0]
            if os.path.isfile(a):
                self._single_file_open(a)
            else:
                tab = self.append_vcview([a], auto_compare)
                    
        elif len(paths) in (2, 3, 4):
            tab = self.append_diff(paths, auto_compare)
        return tab

