package dev.synesis.poc.ui;

import java.awt.*;
import javax.swing.*;
import javax.swing.border.EmptyBorder;

/** Small shared vector controls; no image decoding, timer or per-frame state. */
public final class PanelCloseButtons {
    private static final Icon CROSS=icon(false),RIGHT=icon(true);
    private static final BasicStroke STROKE=new BasicStroke(1.4f,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND);
    private PanelCloseButtons() {}

    public static JButton close(String label,Runnable action){return button(CROSS,label,action);}
    public static JButton collapseRight(String label,Runnable action){return button(RIGHT,label,action);}
    public static JButton expand(String label,Runnable action){
        return button(new Icon(){
            public int getIconWidth(){return 16;}
            public int getIconHeight(){return 16;}
            public void paintIcon(Component component,Graphics graphics,int x,int y){
                Graphics2D g=(Graphics2D)graphics.create();
                try {
                    g.translate(x,y);g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                    g.setColor(component.getForeground());g.setStroke(STROKE);
                    g.drawLine(2,6,2,2);g.drawLine(2,2,6,2);
                    g.drawLine(10,2,14,2);g.drawLine(14,2,14,6);
                    g.drawLine(14,10,14,14);g.drawLine(14,14,10,14);
                    g.drawLine(6,14,2,14);g.drawLine(2,14,2,10);
                } finally {g.dispose();}
            }
        },label,action);
    }

    private static JButton button(Icon icon,String label,Runnable action) {
        JButton button=new JButton(icon) {
            @Override protected void paintComponent(Graphics graphics) {
                if(icon==PanelCloseButtons.RIGHT) {
                    Graphics2D g=(Graphics2D)graphics.create();
                    try {
                        g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                        g.setColor(getModel().isRollover()?new Color(0xd4e2f4):MistWorkspaceTheme.SOFT);
                        g.fillOval(2,2,getWidth()-4,getHeight()-4);
                    } finally {g.dispose();}
                }
                super.paintComponent(graphics);
            }
        };MistWorkspaceTheme.button(button,false);
        button.setPreferredSize(new Dimension(32,32));button.setMinimumSize(new Dimension(32,32));
        button.setBorder(new EmptyBorder(0,0,0,0));button.setForeground(MistWorkspaceTheme.MUTED);
        button.setToolTipText(label);button.getAccessibleContext().setAccessibleName(label);
        button.addActionListener(event->action.run());return button;
    }
    private static Icon icon(boolean right) {
        return new Icon() {
            public int getIconWidth(){return 16;}
            public int getIconHeight(){return 16;}
            public void paintIcon(Component component,Graphics graphics,int x,int y) {
                Graphics2D g=(Graphics2D)graphics.create();
                try {
                    g.translate(x,y);g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                    g.setColor(component.getForeground());g.setStroke(STROKE);
                    if(right){g.drawLine(6,3,11,8);g.drawLine(11,8,6,13);}
                    else {g.drawLine(4,4,12,12);g.drawLine(4,12,12,4);}
                } finally {g.dispose();}
            }
        };
    }
}
