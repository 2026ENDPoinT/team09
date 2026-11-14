package dev.synesis.poc.ui;

import javax.accessibility.AccessibleAction;
import javax.accessibility.AccessibleContext;
import javax.swing.*;
import javax.swing.text.JTextComponent;
import java.awt.*;

/** Text inputs expose a real focus action to screen readers and macOS automation. */
public final class AccessibleInputs {
    private AccessibleInputs() { }

    private static boolean focus(JTextComponent input, int action) {
        if (action != 0 || !input.isEnabled() || !input.isShowing()) return false;
        SwingUtilities.invokeLater(() -> {
            if (!input.isEnabled() || !input.isShowing()) return;
            // AXPress on a Swing text component otherwise does not focus it.
            // Keyboard input remains ordinary OS input, with no automation backdoor.
            if (Desktop.isDesktopSupported() && Desktop.getDesktop().isSupported(Desktop.Action.APP_REQUEST_FOREGROUND)) {
                Desktop.getDesktop().requestForeground(true);
            }
            Window window = SwingUtilities.getWindowAncestor(input);
            if (window != null) {
                window.toFront();
                window.requestFocus();
            }
            input.requestFocusInWindow();
        });
        return true;
    }

    public static class TextArea extends JTextArea {
        @Override public AccessibleContext getAccessibleContext() {
            if (accessibleContext == null) accessibleContext = new AccessibleInput();
            return accessibleContext;
        }
        protected class AccessibleInput extends AccessibleJTextArea implements AccessibleAction {
            @Override public AccessibleAction getAccessibleAction() { return this; }
            @Override public int getAccessibleActionCount() { return isEnabled() ? 1 : 0; }
            @Override public String getAccessibleActionDescription(int index) {
                return index == 0 ? AccessibleAction.CLICK : null;
            }
            @Override public boolean doAccessibleAction(int index) { return focus(TextArea.this, index); }
        }
    }

    public static class TextField extends JTextField {
        @Override public AccessibleContext getAccessibleContext() {
            if (accessibleContext == null) accessibleContext = new AccessibleInput();
            return accessibleContext;
        }
        protected class AccessibleInput extends AccessibleJTextField implements AccessibleAction {
            @Override public AccessibleAction getAccessibleAction() { return this; }
            @Override public int getAccessibleActionCount() { return isEnabled() ? 1 : 0; }
            @Override public String getAccessibleActionDescription(int index) {
                return index == 0 ? AccessibleAction.CLICK : null;
            }
            @Override public boolean doAccessibleAction(int index) { return focus(TextField.this, index); }
        }
    }
}
