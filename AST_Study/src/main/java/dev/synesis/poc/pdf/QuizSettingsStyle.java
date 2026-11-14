package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.MistWorkspaceTheme;

import dev.synesis.poc.ui.LibraryDesign;
import dev.synesis.poc.ui.StudyTheme;
import java.awt.*;
import javax.swing.*;
import javax.swing.border.EmptyBorder;
import javax.swing.plaf.basic.BasicButtonUI;
import javax.swing.plaf.basic.BasicCheckBoxUI;

/** Local surfaces for the workbook settings; no application-wide control overrides. */
final class QuizSettingsStyle {
    static final Color INK=new Color(0x262a30),LINE=new Color(0xdfe9f7),SOFT=MistWorkspaceTheme.SOFT,MUTED=new Color(0x777e89);
    private QuizSettingsStyle(){}

    static void button(AbstractButton button,boolean primary) {
        button.setFont(StudyTheme.font(primary?Font.BOLD:Font.PLAIN,12));
        button.setForeground(primary?Color.WHITE:INK);button.setOpaque(false);
        button.setContentAreaFilled(false);button.setBorderPainted(false);button.setFocusPainted(false);
        button.setRolloverEnabled(true);button.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));
        button.setBorder(new EmptyBorder(10,14,10,14));
        button.putClientProperty("synesis.preserveFont",true);button.putClientProperty("synesis.preserveButton",true);
        button.setUI(new BasicButtonUI(){
            @Override public void paint(Graphics graphics,JComponent component){
                Graphics2D g=(Graphics2D)graphics.create();
                try {
                    g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                    g.setColor(primary?(button.getModel().isRollover()?new Color(0x41464e):INK)
                        :(button.getModel().isRollover()?SOFT:Color.WHITE));
                    g.fillRoundRect(0,0,component.getWidth(),component.getHeight(),16,16);
                    g.setColor(button.hasFocus()?INK:primary?INK:LINE);
                    g.drawRoundRect(0,0,component.getWidth()-1,component.getHeight()-1,16,16);
                }finally{g.dispose();}
                super.paint(graphics,component);
            }
        });
    }

    static void spinner(JSpinner spinner,int width) {
        spinner.setFont(StudyTheme.font(Font.PLAIN,13));spinner.setBackground(Color.WHITE);
        spinner.setPreferredSize(new Dimension(width,36));
        spinner.setBorder(new LibraryDesign.RoundedBorder(8,LINE,new Insets(4,8,4,4)));
        if(spinner.getEditor() instanceof JSpinner.DefaultEditor editor){
            JFormattedTextField input=editor.getTextField();input.setFont(StudyTheme.font(Font.PLAIN,13));
            input.setForeground(INK);input.setBackground(Color.WHITE);input.setBorder(new EmptyBorder(0,0,0,4));
            input.putClientProperty("synesis.preserveFont",true);
        }
    }

    static void format(JCheckBox box) {
        box.setFont(StudyTheme.font(Font.PLAIN,12));box.setForeground(INK);
        box.setOpaque(false);box.setContentAreaFilled(false);box.setFocusPainted(false);
        box.setBorder(new EmptyBorder(12,12,12,8));box.setBorderPainted(false);
        box.setIconTextGap(9);box.setRolloverEnabled(true);box.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));
        box.setIcon(new Icon(){
            public int getIconWidth(){return 16;}public int getIconHeight(){return 16;}
            public void paintIcon(Component component,Graphics graphics,int x,int y){
                Graphics2D g=(Graphics2D)graphics.create();
                try {
                    g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                    g.setColor(box.isSelected()?INK:Color.WHITE);g.fillRoundRect(x,y,16,16,6,6);
                    g.setColor(box.isSelected()?INK:new Color(0xc5cbd3));g.drawRoundRect(x,y,15,15,6,6);
                    if(box.isSelected()){
                        g.setColor(Color.WHITE);g.setStroke(new BasicStroke(1.7f,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));
                        g.drawLine(x+4,y+8,x+7,y+11);g.drawLine(x+7,y+11,x+12,y+5);
                    }
                }finally{g.dispose();}
            }
        });
        box.setUI(new BasicCheckBoxUI(){
            @Override public void paint(Graphics graphics,JComponent component){
                Graphics2D g=(Graphics2D)graphics.create();
                try {
                    g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                    g.setColor(box.isSelected()?MistWorkspaceTheme.SOFT:Color.WHITE);
                    g.fillRoundRect(0,0,box.getWidth(),box.getHeight(),18,18);
                    g.setColor(box.hasFocus()?INK:box.isSelected()?new Color(0xbac1cb):LINE);
                    g.drawRoundRect(0,0,box.getWidth()-1,box.getHeight()-1,18,18);
                }finally{g.dispose();}
                super.paint(graphics,component);
            }
        });
        box.addItemListener(event->box.repaint());
    }
}
