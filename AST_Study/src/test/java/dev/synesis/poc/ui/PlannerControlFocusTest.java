package dev.synesis.poc.ui;

import javax.swing.*;
import javax.swing.plaf.basic.BasicComboBoxUI;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.util.Arrays;

/** Closed controls keep their normal colors; dropdown choices and keyboard actions remain live. */
public final class PlannerControlFocusTest {
    private static int checks;
    private static void check(boolean value, String message) { checks++; if (!value) throw new AssertionError(message); }
    public static void main(String[] args) throws Exception {
        SwingUtilities.invokeAndWait(() -> {
            UIManager.put("ComboBoxUI", PlainComboBoxUI.class.getName());
            for (int style = 0; style < 4; style++) {
                JComboBox<String> combo = style == 1 ? PlannerStyle.combo("반복", new String[]{"반복 안 함", "매일", "매주"}) :
                    new JComboBox<>(new String[]{"반복 안 함", "매일", "매주"});
                if (style == 2) StudyTheme.comboBox(combo);
                if (style == 3) MistWorkspaceTheme.comboBox(combo, true);
                combo.setSize(270, 36); combo.doLayout();
                int[] actions = {0}; combo.addActionListener(e -> actions[0]++);
                combo.setSelectedItem("매일");
                check(actions[0] == 1 && "매일".equals(combo.getSelectedItem()), "selected repeat value/action, style " + style);
                check(Arrays.equals(paintValue(combo, false), paintValue(combo, true)), "closed combo retained focus selection fill, style " + style);
                check(combo.isFocusable(), "combo lost keyboard focusability, style " + style);
                check(combo.getActionMap().get("selectNext") != null, "combo lost keyboard arrow action, style " + style);
                JList<String> list = new JList<>(new String[]{"매일"});
                Component row = combo.getRenderer().getListCellRendererComponent(list, "매일", 0, true, false);
                Color selected = row.getBackground();
                row = combo.getRenderer().getListCellRendererComponent(list, "매일", 0, false, false);
                check(!selected.equals(row.getBackground()), "open list no longer highlights its active choice, style " + style);
            }
            JComboBox<String> editable = PlannerStyle.combo("시작 시간", new String[]{"10:00", "11:00"});
            editable.setEditable(true);
            check(editable.getEditor().getEditorComponent() instanceof JTextField, "editable time combo lost text input");
            editable.getEditor().setItem("14:30");
            check("14:30".equals(editable.getEditor().getItem()), "custom typed time lost");
            JCheckBox check = PlannerStyle.check("종일");
            check.doClick(0);
            check(check.isSelected() && !check.getModel().isPressed() && !check.getModel().isArmed(), "checkbox retains setting but releases press state");
            JButton save = PlannerStyle.button("저장", true, () -> {});
            save.doClick(0);
            check(!save.getModel().isPressed() && !save.getModel().isArmed() && save.isFocusable(), "button finishes click and retains keyboard access");
        });
        System.out.println("PASS: " + checks + " closed-control colors, dropdown choices, keyboard/click checks");
    }
    private static int[] paintValue(JComboBox<?> combo, boolean focus) {
        BufferedImage image = new BufferedImage(240, 32, BufferedImage.TYPE_INT_ARGB);
        Graphics2D graphics = image.createGraphics();
        BasicComboBoxUI ui = (BasicComboBoxUI) combo.getUI();
        ui.paintCurrentValueBackground(graphics, new Rectangle(0, 0, 240, 32), focus);
        ui.paintCurrentValue(graphics, new Rectangle(0, 0, 240, 32), focus);
        graphics.dispose();
        return image.getRGB(0, 0, 240, 32, null, 0, 240);
    }
}
