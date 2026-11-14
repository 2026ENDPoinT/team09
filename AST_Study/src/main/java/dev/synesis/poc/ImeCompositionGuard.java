package dev.synesis.poc;

import javax.swing.*;
import javax.swing.text.*;
import java.awt.*;
import java.awt.event.*;
import java.awt.im.InputContext;
import java.lang.ref.WeakReference;
import java.text.AttributedCharacterIterator;
import java.text.CharacterIterator;
import java.util.Map;
import java.util.WeakHashMap;

/** One IME boundary for every Swing text input, including lazily created dialogs/editors. */
final class ImeCompositionGuard implements AWTEventListener, KeyEventDispatcher {
    private static ImeCompositionGuard installed;
    private WeakReference<JTextComponent> composing = new WeakReference<>(null);
    // macOS can post the native confirmation after endComposition() has returned.
    // Remember only the one confirmation already applied to its original component.
    private record Confirmation(String value, WeakReference<InputContext> context) {}
    private final Map<JTextComponent, Confirmation> confirmations = new WeakHashMap<>();
    private WeakReference<JTextComponent> confirmingEnter = new WeakReference<>(null);
    private boolean finishing;

    static synchronized void install() {
        if (installed != null) return;
        installed = new ImeCompositionGuard();
        Toolkit.getDefaultToolkit().addAWTEventListener(installed,
            AWTEvent.INPUT_METHOD_EVENT_MASK | AWTEvent.MOUSE_EVENT_MASK |
            AWTEvent.FOCUS_EVENT_MASK | AWTEvent.WINDOW_FOCUS_EVENT_MASK |
            AWTEvent.WINDOW_EVENT_MASK | AWTEvent.HIERARCHY_EVENT_MASK |
            AWTEvent.CONTAINER_EVENT_MASK);
        KeyboardFocusManager.getCurrentKeyboardFocusManager().addKeyEventDispatcher(installed);
    }

    @Override public void eventDispatched(AWTEvent event) {
        if (finishing) return;
        if (event instanceof InputMethodEvent input && input.getSource() instanceof JTextComponent text) {
            if (input.getID() != InputMethodEvent.INPUT_METHOD_TEXT_CHANGED || input.isConsumed()) return;
            String value = characters(input.getText());
            Confirmation confirmed = confirmations.remove(text);
            if (input.getCommittedCharacterCount() == value.length() &&
                (confirmed != null && confirmed.value().equals(value) || redirectedConfirmation(text, value))) {
                input.consume(); // Do not insert the same native confirmation a second time.
                return;
            }
            if (value.length() > input.getCommittedCharacterCount()) {
                // If focus has already moved, never end the new client's shared native context.
                if (composing.get() != null && composing.get() != text) finish(false);
                clearConfirmations(text.getInputContext());
                composing = new WeakReference<>(text);
            } else if (composing.get() == text) composing.clear();
        } else if (event instanceof MouseEvent mouse && mouse.getID() == MouseEvent.MOUSE_PRESSED) {
            // A deliberate click also finalizes text before repositioning the caret in the same input.
            if (composing.get() != null) finish();
        } else if (event instanceof FocusEvent focus) {
            if (focus.getID() == FocusEvent.FOCUS_LOST && focus.getComponent() == composing.get()) finish();
            else if (focus.getID() == FocusEvent.FOCUS_GAINED && composing.get() != null &&
                focus.getComponent() != composing.get()) finish(false);
        } else if (event instanceof WindowEvent window) {
            if (window.getID() == WindowEvent.WINDOW_DEACTIVATED || window.getID() == WindowEvent.WINDOW_LOST_FOCUS ||
                window.getID() == WindowEvent.WINDOW_CLOSING || window.getID() == WindowEvent.WINDOW_CLOSED) {
                JTextComponent text = composing.get();
                if (text != null && SwingUtilities.getWindowAncestor(text) == window.getWindow()) finish();
            }
        } else if (event instanceof HierarchyEvent hierarchy &&
            (hierarchy.getChangeFlags() & (HierarchyEvent.SHOWING_CHANGED | HierarchyEvent.DISPLAYABILITY_CHANGED)) != 0) {
            JTextComponent text = composing.get();
            if (text != null && inside(text, hierarchy.getComponent()) && !text.isShowing()) finish();
        } else if (event instanceof ContainerEvent container && container.getID() == ContainerEvent.COMPONENT_REMOVED) {
            if (composing.get() != null && inside(composing.get(), container.getChild())) finish();
        }
    }

    @Override public boolean dispatchKeyEvent(KeyEvent event) {
        if (event.getComponent() == confirmingEnter.get()) {
            if (event.getID() == KeyEvent.KEY_TYPED && event.getKeyChar() == '\n') return true;
            if (event.getID() == KeyEvent.KEY_RELEASED && event.getKeyCode() == KeyEvent.VK_ENTER) confirmingEnter.clear();
        }
        if (event.getID() != KeyEvent.KEY_PRESSED) return false;
        if (event.getComponent() instanceof JTextComponent text) {
            confirmations.remove(text);
            if (!event.isControlDown() && !event.isMetaDown() && event.getKeyChar() >= ' ' &&
                event.getKeyChar() != KeyEvent.CHAR_UNDEFINED && event.getKeyChar() != 127)
                clearConfirmations(text.getInputContext());
        }
        JTextComponent text = composing.get();
        if (text == null || event.getComponent() != text) return false;
        if (event.getKeyCode() == KeyEvent.VK_TAB) finish();
        else if (event.getKeyCode() == KeyEvent.VK_ENTER) {
            finish();
            confirmingEnter = new WeakReference<>(text);
            return true; // First Enter confirms IME text; a subsequent Enter submits/inserts a newline.
        }
        return false;
    }

    void finish() { finish(true); }

    private void finish(boolean endNative) {
        JTextComponent text = composing.get();
        if (finishing || text == null) return;
        finishing = true;
        try {
            if (endNative) {
                InputContext context = text.getInputContext();
                if (context != null) context.endComposition();
            }
            // An end request alone does not clear Swing's composed-document range on macOS.
            // Let Swing retire its composed range AND its private caret/IME state, then insert
            // the accepted text normally. A whole-value setText() would disturb surrounding
            // content; a committed-text key event can interpret control characters as actions.
            CompositionRange range = composedRange(text.getDocument().getDefaultRootElement());
            if (range != null && text.isEditable()) {
                int start = range.start();
                int end = Math.min(range.end(), text.getDocument().getLength());
                String value = text.getDocument().getText(start, end - start);
                text.setCaretPosition(end);
                confirmations.put(text, new Confirmation(value, new WeakReference<>(text.getInputContext())));
                text.dispatchEvent(new InputMethodEvent(text, InputMethodEvent.INPUT_METHOD_TEXT_CHANGED,
                    null, 0, null, null));
                text.setCaretPosition(start);
                text.replaceSelection(value);
            }
            composing.clear();
        } catch (BadLocationException impossible) {
            throw new IllegalStateException("IME document changed during composition commit", impossible);
        } finally {
            finishing = false;
        }
    }

    private record CompositionRange(int start, int end) {}

    private boolean redirectedConfirmation(JTextComponent target, String value) {
        // Cocoa may address its queued unmarkText to the newly focused client of the same
        // InputContext. It still confirms the previous client's text, already preserved above.
        if (value.isEmpty() || composing.get() == target || composedRange(target.getDocument().getDefaultRootElement()) != null)
            return false;
        InputContext context = target.getInputContext();
        if (context == null) return false;
        var iterator = confirmations.entrySet().iterator();
        while (iterator.hasNext()) {
            var entry = iterator.next();
            Confirmation pending = entry.getValue();
            if (entry.getKey() != target && pending.context().get() == context && pending.value().equals(value)) {
                iterator.remove();
                return true;
            }
        }
        return false;
    }

    private void clearConfirmations(InputContext context) {
        if (context != null) confirmations.values().removeIf(value -> value.context().get() == context);
    }

    private static CompositionRange composedRange(Element element) {
        if (element.getAttributes().isDefined(StyleConstants.ComposedTextAttribute))
            return new CompositionRange(element.getStartOffset(), element.getEndOffset());
        CompositionRange range = null;
        for (int i = 0; i < element.getElementCount(); i++) {
            CompositionRange result = composedRange(element.getElement(i));
            if (result != null) range = range == null ? result :
                new CompositionRange(Math.min(range.start(), result.start()), Math.max(range.end(), result.end()));
        }
        return range;
    }

    private static boolean inside(Component child, Component parent) {
        return child == parent || child != null && parent != null && SwingUtilities.isDescendingFrom(child, parent);
    }

    private static String characters(AttributedCharacterIterator value) {
        if (value == null) return "";
        StringBuilder result = new StringBuilder();
        for (char c = value.first(); c != CharacterIterator.DONE; c = value.next()) result.append(c);
        return result.toString();
    }
}
