package dev.synesis.poc;

import dev.synesis.poc.ui.FadingScrollBarUI;

import javax.swing.*;
import javax.swing.plaf.FontUIResource;
import javax.swing.plaf.ColorUIResource;
import javax.swing.plaf.BorderUIResource;
import java.awt.*;
import java.util.Enumeration;

/** Use the same Korean typeface for standard Swing controls and dialogs. */
public final class UiFonts {
    public static final String FAMILY = selectFamily();

    private UiFonts() {}

    private static String selectFamily() {
        var installed = java.util.Set.of(GraphicsEnvironment.getLocalGraphicsEnvironment().getAvailableFontFamilyNames());
        for (String name : new String[] {"Noto Sans KR", "Apple SD Gothic Neo", "Nanum Gothic", "Malgun Gothic"}) {
            if (installed.contains(name) && new Font(name, Font.PLAIN, 13).canDisplayUpTo("강의자료") == -1)
                return name;
        }
        return Font.DIALOG;
    }

    static void install() {
        // Disable hover tooltips across every screen, including controls created later.
        // Keep their text available to accessibility names and outline metadata.
        ToolTipManager.sharedInstance().setEnabled(false);
        ImeCompositionGuard.install();
        UIManager.put("ComboBoxUI", dev.synesis.poc.ui.PlainComboBoxUI.class.getName());
        UIManager.put("PopupMenuUI", dev.synesis.poc.ui.RoundedPopupMenuUI.class.getName());
        UIManager.put("PopupMenu.background", new ColorUIResource(Color.WHITE));
        UIManager.put("MenuItem.selectionBackground", new ColorUIResource(Color.WHITE));
        UIManager.put("MenuItem.selectionForeground", new ColorUIResource(Color.BLACK));
        UIManager.put("ScrollBarUI", FadingScrollBarUI.class.getName());
        installFocusAppearance();
        UIDefaults defaults = UIManager.getLookAndFeelDefaults();
        for (Enumeration<Object> keys = defaults.keys(); keys.hasMoreElements();) {
            Object key = keys.nextElement();
            Object value = defaults.get(key);
            if (value instanceof Font font) {
                defaults.put(key, new FontUIResource(FAMILY, font.getStyle(), font.getSize()));
            }
        }
    }

    /** Keep focus/keyboard behavior, without click/focus outlines on standard controls. */
    private static void installFocusAppearance() {
        Color transparent=new ColorUIResource(new Color(0,0,0,0));
        for(String key:new String[]{"Focus.color","Button.focus","ToggleButton.focus",
            "RadioButton.focus","CheckBox.focus","Slider.focus","TabbedPane.focus",
            "ComboBox.focus","Tree.selectionBorderColor"})UIManager.put(key,transparent);
        UIManager.put("Component.focusWidth",0);
        UIManager.put("Component.innerFocusWidth",0);
        // Preserve cell padding so focus cannot shift text or change row geometry.
        for(String key:new String[]{"List.focusCellHighlightBorder","List.focusSelectedCellHighlightBorder",
            "Table.focusCellHighlightBorder","Table.focusSelectedCellHighlightBorder","TableHeader.focusCellBorder"}){
            javax.swing.border.Border border=UIManager.getBorder(key);
            if(border!=null){
                Insets padding=border.getBorderInsets(new JLabel());
                UIManager.put(key,new BorderUIResource.EmptyBorderUIResource(padding));
            }
        }
    }
}
