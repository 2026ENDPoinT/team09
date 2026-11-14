package dev.synesis.poc;

import javax.swing.*;
import javax.swing.text.*;
import java.awt.*;
import java.awt.event.*;
import java.awt.im.InputContext;
import java.awt.im.InputMethodHighlight;
import java.awt.font.TextAttribute;
import java.text.AttributedString;
import java.util.List;

/** Real Swing composed documents, with deterministic native confirmation timing. No OS keystrokes. */
public final class ImeCompositionGuardTest {
    private static int checks;
    private static void check(boolean value, String message) {
        checks++;
        if (!value) throw new AssertionError(message);
    }
    static class Context extends InputContext {
        int commits;
        Runnable commit = () -> {};
        @Override public void endComposition() { commits++; commit.run(); }
    }
    record Input(JTextComponent text, Context context) {}
    static Input input(int kind) {
        Context context = new Context();
        JTextComponent text = switch (kind) {
            case 0 -> new JTextField() { @Override public InputContext getInputContext() { return context; } };
            case 1 -> new JTextArea() { @Override public InputContext getInputContext() { return context; } };
            case 2 -> new JTextPane() { @Override public InputContext getInputContext() { return context; } };
            case 3 -> new JEditorPane() { @Override public InputContext getInputContext() { return context; } };
            case 4 -> new JPasswordField() { @Override public InputContext getInputContext() { return context; } };
            case 5 -> new JFormattedTextField() { @Override public InputContext getInputContext() { return context; } };
            case 6 -> new dev.synesis.poc.ui.AccessibleInputs.TextField() { @Override public InputContext getInputContext() { return context; } };
            case 7 -> new dev.synesis.poc.ui.AccessibleInputs.TextArea() { @Override public InputContext getInputContext() { return context; } };
            case 8 -> (JTextComponent) new JComboBox<String>(new String[]{"10:00"}) {{ setEditable(true); }}.getEditor().getEditorComponent();
            case 9 -> ((JSpinner.DefaultEditor) new JSpinner().getEditor()).getTextField();
            default -> throw new AssertionError();
        };
        return new Input(text, context);
    }
    static void emit(ImeCompositionGuard guard, JTextComponent text, String value, int committed) {
        AttributedString attributed = value == null ? null : new AttributedString(value);
        if (attributed != null && committed < value.length())
            attributed.addAttribute(TextAttribute.INPUT_METHOD_HIGHLIGHT, InputMethodHighlight.UNSELECTED_RAW_TEXT_HIGHLIGHT, committed, value.length());
        InputMethodEvent event = new InputMethodEvent(text, InputMethodEvent.INPUT_METHOD_TEXT_CHANGED,
            attributed == null ? null : attributed.getIterator(), committed, null, null);
        guard.eventDispatched(event);
        text.dispatchEvent(event);
    }
    static boolean pending(JTextComponent text) {
        return text.getDocument().getLength() != text.getInputMethodRequests().getCommittedTextLength();
    }
    static void settled(JTextComponent text, String expected, String message) {
        check(text.getText().equals(expected), message + ": text was " + text.getText());
        check(!pending(text), message + ": document still contains composed text");
    }
    static MouseEvent click(Component component) {
        return new MouseEvent(component, MouseEvent.MOUSE_PRESSED, 0, 0, 1, 1, 1, false);
    }
    static KeyEvent key(Component component, int id, int code, char value) {
        return new KeyEvent(component, id, 0, 0, code, value);
    }
    public static void main(String[] args) throws Exception {
        SwingUtilities.invokeAndWait(() -> {
            for (int kind = 0; kind < 10; kind++) {
                ImeCompositionGuard guard = new ImeCompositionGuard();
                Input input = input(kind); JTextComponent text = input.text();
                // The spinner's numeric formatter intentionally rejects Korean text.
                if (text instanceof JFormattedTextField formatted) formatted.setFormatterFactory(null);
                text.setText("앞뒤"); text.setCaretPosition(1);
                emit(guard, text, "한글", 0);
                check(pending(text), "real composed range created, type " + kind);
                guard.eventDispatched(click(text));
                settled(text, "앞한글뒤", "same-field caret click finalizes composition, type " + kind);
                guard.dispatchKeyEvent(key(text, KeyEvent.KEY_PRESSED, KeyEvent.VK_G, 'g'));
                emit(guard, text, "자", 0);
                guard.eventDispatched(click(new JButton("저장")));
                settled(text, "앞한글자뒤", "button boundary, type " + kind);
                emit(guard, text, "자", 1);
                settled(text, "앞한글자뒤", "late native confirmation must not duplicate, type " + kind);
                guard.eventDispatched(new FocusEvent(text, FocusEvent.FOCUS_LOST));
                settled(text, "앞한글자뒤", "following focus loss is idempotent, type " + kind);
            }
            for (Component target : List.of(new JButton("저장"), new JCheckBox("종일"), new JComboBox<>(new String[]{"매일"}),
                new JSpinner(), new JLabel("빈 영역"), new JPanel(), new JList<>(), new JMenuItem("수정"))) {
                ImeCompositionGuard guard = new ImeCompositionGuard(); Input input = input(1);
                emit(guard, input.text(), "마지막글자", 0);
                guard.eventDispatched(click(target));
                settled(input.text(), "마지막글자", "click " + target.getClass().getSimpleName());
                check(input.context().commits == 1, "native context ended once before control action");
            }
            ImeCompositionGuard guard = new ImeCompositionGuard(); Input first = input(0), second = input(1);
            emit(guard, first.text(), "한", 0);
            guard.eventDispatched(new FocusEvent(first.text(), FocusEvent.FOCUS_LOST, true, second.text()));
            settled(first.text(), "한", "temporary focus loss");
            emit(guard, second.text(), "글", 0);
            emit(guard, first.text(), "한", 1);
            settled(first.text(), "한", "late old confirmation after new field starts");
            check(pending(second.text()) && second.context().commits == 0, "new field composition untouched");
            guard.finish(); settled(second.text(), "글", "new field independently settles");

            guard = new ImeCompositionGuard(); first = input(0); second = input(1);
            emit(guard, first.text(), "이전", 0); emit(guard, second.text(), "다음", 0);
            settled(first.text(), "이전", "missed focus boundary still retires original Swing composition");
            check(first.context().commits == 0 && second.context().commits == 0, "never end the new client's shared native context");
            guard.finish(); settled(second.text(), "다음", "second client remains usable");

            for (int code : new int[]{KeyEvent.VK_TAB, KeyEvent.VK_ENTER}) {
                guard = new ImeCompositionGuard(); first = input(1);
                emit(guard, first.text(), "완성", 0);
                boolean consumed = guard.dispatchKeyEvent(key(first.text(), KeyEvent.KEY_PRESSED, code, code == KeyEvent.VK_TAB ? '\t' : '\n'));
                settled(first.text(), "완성", "keyboard boundary " + code);
                check(consumed == (code == KeyEvent.VK_ENTER), "Tab navigation preserved; composing Enter confirms without sending");
                if (code == KeyEvent.VK_ENTER) {
                    check(guard.dispatchKeyEvent(key(first.text(), KeyEvent.KEY_TYPED, KeyEvent.VK_UNDEFINED, '\n')), "paired newline cannot leak into the input");
                    guard.dispatchKeyEvent(key(first.text(), KeyEvent.KEY_RELEASED, code, '\n'));
                    check(!guard.dispatchKeyEvent(key(first.text(), KeyEvent.KEY_PRESSED, code, '\n')), "next Enter retains normal submit/newline action");
                }
            }
            guard = new ImeCompositionGuard(); first = input(0);
            emit(guard, first.text(), "한", 0); guard.finish();
            guard.dispatchKeyEvent(key(first.text(), KeyEvent.KEY_PRESSED, KeyEvent.VK_G, 'g'));
            emit(guard, first.text(), "한", 1);
            settled(first.text(), "한한", "same syllable typed later must not be mistaken for late confirmation");

            guard = new ImeCompositionGuard(); first = input(1);
            first.text().setText("앞지울말뒤"); first.text().select(1, 4);
            emit(guard, first.text(), "공부하자", 2); guard.finish();
            settled(first.text(), "앞공부하자뒤", "selection replacement with partially committed IME text");

            guard = new ImeCompositionGuard(); first = input(1);
            emit(guard, first.text(), "한\n글", 0);
            String accepted = first.text().getText(); // PlainDocument normalizes composed newlines itself.
            guard.finish();
            settled(first.text(), accepted, "all text accepted by the document is preserved");

            guard = new ImeCompositionGuard(); first = input(2);
            emit(guard, first.text(), "여러스타일", 0);
            SimpleAttributeSet bold = new SimpleAttributeSet(); StyleConstants.setBold(bold, true);
            ((StyledDocument) first.text().getDocument()).setCharacterAttributes(1, 2, bold, false);
            guard.finish(); settled(first.text(), "여러스타일", "composed range split across styled leaves");

            guard = new ImeCompositionGuard(); first = input(0);
            ImeCompositionGuard reentrantGuard = guard;
            first.context().commit = reentrantGuard::finish;
            emit(guard, first.text(), "재진입", 0); guard.finish();
            settled(first.text(), "재진입", "reentrant endComposition callback");
            check(first.context().commits == 1, "no recursive native end calls");

            guard = new ImeCompositionGuard(); first = input(0);
            ImeCompositionGuard syncGuard = guard; JTextComponent syncText = first.text();
            first.context().commit = () -> emit(syncGuard, syncText, "즉시", 2);
            emit(guard, first.text(), "즉시", 0); guard.finish();
            settled(first.text(), "즉시", "synchronous native confirmation does not need fallback");
            guard.dispatchKeyEvent(key(first.text(), KeyEvent.KEY_PRESSED, KeyEvent.VK_W, 'w'));
            emit(guard, first.text(), "즉시", 2);
            settled(first.text(), "즉시즉시", "normal subsequent commit after synchronous confirmation");

            guard = new ImeCompositionGuard(); first = input(0);
            emit(guard, first.text(), "취소", 0); emit(guard, first.text(), null, 0); guard.finish();
            settled(first.text(), "", "IME cancellation remains cancellation");
            check(first.context().commits == 0, "already cancelled composition is not re-committed");

            Context shared = new Context();
            JTextField oldInput = new JTextField("제목") { @Override public InputContext getInputContext() { return shared; } };
            JTextArea newInput = new JTextArea("설명") { @Override public InputContext getInputContext() { return shared; } };
            guard = new ImeCompositionGuard(); oldInput.setCaretPosition(oldInput.getDocument().getLength());
            emit(guard, oldInput, "ㅎ", 0); guard.finish();
            newInput.selectAll();
            emit(guard, newInput, "ㅎ", 1);
            settled(oldInput, "제목ㅎ", "shared-context original text remains committed");
            settled(newInput, "설명", "redirected native confirmation cannot replace selected text in another field");
            emit(guard, oldInput, "ㄱ", 0); guard.finish();
            guard.dispatchKeyEvent(key(newInput, KeyEvent.KEY_PRESSED, KeyEvent.VK_R, 'r'));
            emit(guard, newInput, "ㄱ", 1);
            settled(newInput, "ㄱ", "new typed identical character on the shared context must not be swallowed");
            emit(guard, oldInput, "ㄴ", 0); guard.finish();
            emit(guard, newInput, "ㄴ", 0); emit(guard, newInput, "ㄴ", 1);
            settled(newInput, "ㄱㄴ", "a new preedit owns its own native confirmation");

            guard = new ImeCompositionGuard(); first = input(0);
            JPanel row = new JPanel(); row.add(first.text()); JPanel parent = new JPanel(); parent.add(row);
            emit(guard, first.text(), "닫기", 0);
            guard.eventDispatched(new ContainerEvent(parent, ContainerEvent.COMPONENT_REMOVED, row));
            settled(first.text(), "닫기", "removing an editor subtree retires composition");
            guard = new ImeCompositionGuard(); first = input(0);
            emit(guard, first.text(), "숨김", 0);
            guard.eventDispatched(new HierarchyEvent(first.text(), HierarchyEvent.HIERARCHY_CHANGED, first.text(), null, HierarchyEvent.SHOWING_CHANGED));
            settled(first.text(), "숨김", "hidden editor retires composition");
        });
        ImeCompositionGuard asyncGuard = new ImeCompositionGuard(); Input async = input(0);
        SwingUtilities.invokeAndWait(() -> {
            async.context().commit = () -> SwingUtilities.invokeLater(() -> emit(asyncGuard, async.text(), "지연", 2));
            emit(asyncGuard, async.text(), "지연", 0); asyncGuard.finish();
            settled(async.text(), "지연", "commit available immediately to save/action listeners");
        });
        SwingUtilities.invokeAndWait(() -> settled(async.text(), "지연", "queued native confirmation neither duplicates nor restores underline"));
        SwingUtilities.invokeAndWait(() -> {
            ImeCompositionGuard.install(); ImeCompositionGuard.install();
            JTextArea text = new JTextArea();
            text.dispatchEvent(new InputMethodEvent(text, InputMethodEvent.INPUT_METHOD_TEXT_CHANGED,
                new AttributedString("전역").getIterator(), 0, null, null));
            check(pending(text), "Toolkit observes real component event dispatch");
            JButton save = new JButton("저장");
            save.addActionListener(event -> settled(text, "전역", "save action sees committed text"));
            save.dispatchEvent(click(save)); save.doClick(0);
            text.dispatchEvent(new InputMethodEvent(text, InputMethodEvent.INPUT_METHOD_TEXT_CHANGED,
                new AttributedString("전역").getIterator(), 2, null, null));
            settled(text, "전역", "global listener suppresses queued confirmation");
        });
        System.out.println("PASS: " + checks + " IME document/lifecycle checks (simulated native callbacks; no native OS input)");
    }
}
