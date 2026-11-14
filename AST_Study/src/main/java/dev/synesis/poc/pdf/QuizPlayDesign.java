package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.LibraryMotionClock;
import dev.synesis.poc.ui.MistWorkspaceTheme;
import java.awt.*;
import java.awt.event.*;
import java.awt.geom.*;
import javax.swing.*;
import javax.swing.border.EmptyBorder;

/** Reading skin with semantic answer feedback. Native vectors and shared motion. */
final class QuizPlayDesign {
    static final Color INK=new Color(0x171717),TEXT=new Color(0x414141),MUTED=new Color(0x777777),
        LINE=new Color(0xdedede),SOFT=new Color(0xf1f1f1),PAGE=Color.WHITE;
    static final Color CORRECT=new Color(0x15803d),INCORRECT=new Color(0xb91c1c),EXPLANATION=TEXT,
        CORRECT_SOFT=new Color(0xf0fdf4),INCORRECT_SOFT=new Color(0xfef2f2);
    static final Color QUESTION_PAPER=Color.WHITE;
    private QuizPlayDesign() {}
    static JPanel panel(LayoutManager layout,int padding) {
        return panel(layout,padding,Color.WHITE);
    }
    static JPanel panel(LayoutManager layout,int padding,Color background) {
        JPanel panel=new MistWorkspaceTheme.Panel(layout,18,background,LINE);
        panel.putClientProperty("mist.shadow",null);
        panel.setBorder(new EmptyBorder(padding,padding,padding,padding));return panel;
    }
    static JPanel shadowedQuestion(JPanel card) {
        JPanel wrapper=new JPanel(new BorderLayout()) {
            @Override protected void paintComponent(Graphics graphics) {
                super.paintComponent(graphics);
                Graphics2D g=(Graphics2D)graphics.create();
                try {
                    MistWorkspaceTheme.paintQuizCardShadow(g,new Rectangle(10,16,getWidth()-20,getHeight()-32));
                } finally {g.dispose();}
            }
        };
        wrapper.setOpaque(false);wrapper.setBorder(new EmptyBorder(16,10,16,10));
        wrapper.add(card,BorderLayout.CENTER);
        return wrapper;
    }
    static JLabel label(String text,int size,boolean bold) {
        return MistWorkspaceTheme.label(text,size,INK,bold?Font.BOLD:Font.PLAIN);
    }
    static Button button(String text,boolean primary) {return new Button(text,primary);}
    static final class Banner extends JLabel {
        Banner(){setFont(MistWorkspaceTheme.font(Font.BOLD,13));setForeground(INK);setBorder(new EmptyBorder(14,14,14,14));setIconTextGap(10);}
        @Override protected void paintComponent(Graphics graphics){
            Graphics2D g=(Graphics2D)graphics.create();try{
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                Object result=getClientProperty("quiz.correct");
                boolean correct=Boolean.TRUE.equals(result),graded=result instanceof Boolean;
                g.setColor(graded?(correct?CORRECT_SOFT:INCORRECT_SOFT):SOFT);g.fillRoundRect(1,1,getWidth()-2,getHeight()-2,24,24);
                g.setColor(graded?(correct?CORRECT:INCORRECT):LINE);g.drawRoundRect(1,1,getWidth()-3,getHeight()-3,24,24);
            }finally{g.dispose();}super.paintComponent(graphics);
        }
    }
    static final class Progress extends JComponent implements LibraryMotionClock.Task {
        private double shown,target,from;private long started;
        Progress(){setPreferredSize(new Dimension(1,4));setMinimumSize(new Dimension(0,4));}
        void setProgress(int done,int total) {
            double next=total==0?0:done/(double)total;
            getAccessibleContext().setAccessibleName("전체 "+total+"문제 중 "+done+"문제 완료");
            if(next==target)return;
            target=next;from=shown;started=System.nanoTime();
            if(!isShowing()||LibraryMotionClock.reduced()||!LibraryMotionClock.add(this)){shown=target;repaint();}
        }
        public boolean advance(long now) {
            if(!isShowing()){shown=target;return false;}
            double t=Math.min(1,(now-started)/300_000_000d);shown=from+(target-from)*LibraryMotionClock.ease(t);repaint();return t<1;
        }
        @Override protected void paintComponent(Graphics graphics) {
            Graphics2D g=(Graphics2D)graphics.create();try{
                g.setColor(new Color(0xe5e5e5));g.fillRoundRect(0,0,getWidth(),4,4,4);
                g.setColor(INK);g.fillRoundRect(0,0,(int)Math.round(getWidth()*shown),4,4,4);
            }finally{g.dispose();}
        }
        @Override public void removeNotify(){LibraryMotionClock.remove(this);shown=target;super.removeNotify();}
        @Override public javax.accessibility.AccessibleContext getAccessibleContext(){if(accessibleContext==null)accessibleContext=new AccessibleJComponent(){};return accessibleContext;}
    }
    static class Button extends JButton implements LibraryMotionClock.Task {
        final boolean primary;private double hover,from,target;private long started;
        Button(String text,boolean primary){
            super(text);this.primary=primary;
            putClientProperty("synesis.preserveButton",true);putClientProperty("synesis.preserveFont",true);
            setFont(MistWorkspaceTheme.font(Font.BOLD,12));setForeground(primary?Color.WHITE:TEXT);
            setOpaque(false);setContentAreaFilled(false);setBorderPainted(false);setFocusPainted(false);
            setBorder(new EmptyBorder(11,13,11,13));setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));setIconTextGap(6);
            setRolloverEnabled(true);getModel().addChangeListener(e->hoverTo(isEnabled()&&(getModel().isRollover()||getModel().isPressed())?1:0));
        }
        private void hoverTo(double value){
            if(value==target)return;from=hover;target=value;started=System.nanoTime();
            if(!isShowing()||LibraryMotionClock.reduced()||!LibraryMotionClock.add(this)){hover=target;repaint();}
        }
        public boolean advance(long now){
            if(!isShowing()){hover=target;return false;}
            double t=Math.min(1,(now-started)/150_000_000d);hover=from+(target-from)*LibraryMotionClock.ease(t);repaint();return t<1;
        }
        protected Color fill(){
            if(Boolean.TRUE.equals(getClientProperty("quiz.tab")))return isSelected()?Color.WHITE:SOFT;
            if(!isEnabled())return primary?new Color(0xebebeb):new Color(0xfafafa);
            if(primary||isSelected())return INK;
            int value=255-(int)Math.round(hover*14);return new Color(value,value,value);
        }
        @Override protected void paintComponent(Graphics graphics){
            Graphics2D g=(Graphics2D)graphics.create();try{
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                g.setColor(fill());g.fillRoundRect(1,1,getWidth()-2,getHeight()-2,18,18);
                g.setColor(isFocusOwner()?INK:LINE);g.drawRoundRect(1,1,getWidth()-3,getHeight()-3,18,18);
                super.paintComponent(g);
            }finally{g.dispose();}
        }
        @Override public void removeNotify(){LibraryMotionClock.remove(this);hover=target=0;super.removeNotify();}
    }
    /** Exact 24-unit paths from the Make source, painted directly at the device scale. */
    static Icon icon(String name,int size){return new Icon(){
        public int getIconWidth(){return size;}public int getIconHeight(){return size;}
        public void paintIcon(Component c,Graphics graphics,int x,int y){
            Graphics2D g=(Graphics2D)graphics.create();try{
                g.translate(x,y);g.scale(size/24d,size/24d);g.setColor(c.getForeground());
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                g.setStroke(new BasicStroke(1.8f,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));Path2D p=new Path2D.Double();
                switch(name){
                    case "bookmark"->{p.moveTo(6,4.8);p.curveTo(6,3.806,6.806,3,7.8,3);p.lineTo(16.2,3);p.curveTo(17.194,3,18,3.806,18,4.8);p.lineTo(18,21);p.lineTo(12,17.2);p.lineTo(6,21);p.closePath();}
                    case "check"->{p.moveTo(5,12);p.lineTo(9,16);p.lineTo(19,6);}
                    case "left"->{p.moveTo(15,18);p.lineTo(9,12);p.lineTo(15,6);}
                    case "right"->{p.moveTo(9,18);p.lineTo(15,12);p.lineTo(9,6);}
                    case "x"->{p.moveTo(6,6);p.lineTo(18,18);p.moveTo(18,6);p.lineTo(6,18);}
                    case "grid"->{for(int row:new int[]{3,14})for(int col:new int[]{3,14})g.draw(new RoundRectangle2D.Double(col,row,7,7,2,2));}
                    case "lightbulb"->{p.moveTo(9,18);p.lineTo(15,18);p.moveTo(10,22);p.lineTo(14,22);p.moveTo(8.4,15.5);p.append(new Arc2D.Double(5,2.5,14,14,239,-298,Arc2D.OPEN),true);p.curveTo(14.8,16,14.7,16.5,14.7,17);p.lineTo(9.3,17);p.curveTo(9.3,16.5,9.2,16,8.4,15.5);}
                    default->{}
                }g.draw(p);
            }finally{g.dispose();}
        }
    };}
}
