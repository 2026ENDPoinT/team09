package dev.synesis.poc.ui;

import javax.swing.*;
import javax.swing.plaf.ComponentUI;
import javax.swing.plaf.basic.BasicComboBoxUI;
import javax.swing.plaf.basic.BasicComboPopup;
import javax.swing.plaf.basic.BasicListUI;
import javax.swing.plaf.basic.ComboPopup;
import java.awt.*;

/** Keep the closed value neutral; selection highlighting belongs only to the open popup. */
public class PlainComboBoxUI extends BasicComboBoxUI {
    public static ComponentUI createUI(JComponent component) { return new PlainComboBoxUI(); }

    @Override protected ComboPopup createPopup() {
        return new BasicComboPopup(comboBox) {
            @Override protected void configurePopup() {
                super.configurePopup();
                setUI(new RoundedPopupMenuUI());
                setBorder(RoundedPopupMenuUI.PADDING);
                scroller.setBackground(Color.WHITE);
                scroller.getViewport().setBackground(Color.WHITE);
            }

            @Override protected void configureList() {
                super.configureList();
                list.setBackground(Color.WHITE);
                list.setSelectionBackground(Color.WHITE);
                list.setOpaque(true);
            }

            @Override protected Rectangle computePopupBounds(int x, int y, int width, int height) {
                int needed = list.getPreferredSize().width;
                if (list.getModel().getSize() > comboBox.getMaximumRowCount())
                    needed += scroller.getVerticalScrollBar().getPreferredSize().width;
                return super.computePopupBounds(x, y, Math.max(width, needed + 4), height);
            }

            @Override protected JList<Object> createList() {
                JList<Object> choices = super.createList();
                choices.setUI(new BasicListUI() {
                    @Override protected void paintCell(Graphics graphics, int row, Rectangle bounds,
                            ListCellRenderer<Object> renderer, ListModel<Object> model,
                            ListSelectionModel selection, int leadIndex) {
                        graphics.setColor(Color.WHITE);
                        graphics.fillRect(bounds.x, bounds.y, bounds.width, bounds.height);
                        Component item = renderer.getListCellRendererComponent(list, model.getElementAt(row), row, false, false);
                        item.setBackground(Color.WHITE);
                        rendererPane.paintComponent(graphics, item, list, bounds.x, bounds.y, bounds.width, bounds.height, true);
                        if (selection.isSelectedIndex(row) && bounds.width > 4 && bounds.height > 4) {
                            graphics.setColor(Color.GRAY);
                            graphics.drawRoundRect(bounds.x + 1, bounds.y + 1, bounds.width - 3, bounds.height - 3, 6, 6);
                        }
                    }

                    @Override public void paint(Graphics graphics, JComponent component) {
                        super.paint(graphics, component);
                        Rectangle clip = graphics.getClipBounds();
                        if (clip == null || list.getModel().getSize() < 2) return;
                        int first = list.locationToIndex(clip.getLocation());
                        int last = list.locationToIndex(new Point(clip.x, clip.y + clip.height - 1));
                        Graphics g = graphics.create();
                        try {
                            g.setColor(RoundedPopupMenuUI.DIVIDER);
                            for (int i = first; i >= 0 && i <= last && i + 1 < list.getModel().getSize(); i++) {
                                Rectangle cell = list.getCellBounds(i, i);
                                if (cell == null) continue;
                                int y = cell.y + cell.height - 1;
                                g.drawLine(cell.x + 4, y, cell.x + cell.width - 5, y);
                            }
                        } finally {
                            g.dispose();
                        }
                    }
                });
                return choices;
            }
        };
    }

    @Override public void paintCurrentValue(Graphics graphics, Rectangle bounds, boolean hasFocus) {
        // BasicComboBoxUI overwrites renderer colors with the list selection colors when
        // focused, even after its popup has closed. Do not transfer that highlight here.
        super.paintCurrentValue(graphics, bounds, false);
    }

    @Override public void paintCurrentValueBackground(Graphics graphics, Rectangle bounds, boolean hasFocus) {
        super.paintCurrentValueBackground(graphics, bounds, false);
    }
}
