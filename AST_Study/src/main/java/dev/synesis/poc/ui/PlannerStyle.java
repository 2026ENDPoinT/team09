package dev.synesis.poc.ui;

import javax.imageio.ImageIO;
import javax.swing.*;
import javax.swing.border.*;
import javax.swing.plaf.basic.*;
import java.awt.*;
import java.awt.event.MouseWheelEvent;
import java.awt.image.BufferedImage;
import java.util.*;

/** Shared Figma planner tokens and native, keyboard-accessible controls. */
final class PlannerStyle {
    static final int CARD_TITLE_SIZE=16;
    static final Color NAVY=new Color(0x002860),BORDER=new Color(0xd8e1ee),SURFACE=new Color(0xf5f8fc),
        BLUE_MUTED=new Color(0x7a8ca3),INK=LibraryDesign.INK,MUTED=LibraryDesign.MUTED,WEEKEND=new Color(0xc94c57),ERROR_COLOR=new Color(0xa32c43);
    private static final Map<String,BufferedImage> ICONS=new HashMap<>();
    private PlannerStyle() {}
    static Font regular(int n){return LibraryDesign.font(Font.PLAIN,n);}
    static Font bold(int n){return LibraryDesign.font(Font.BOLD,n);}
    static Font medium(int n){return LibraryDesign.medium(n);}
    static Graphics2D quality(Graphics source){Graphics2D g=(Graphics2D)source.create();g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING,RenderingHints.VALUE_TEXT_ANTIALIAS_ON);g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BICUBIC);return g;}
    static Icon icon(String name,int size){
        BufferedImage image=ICONS.computeIfAbsent(name,key->{try(var in=PlannerStyle.class.getResourceAsStream("/dev/synesis/poc/planner/"+key+".png")){
            if(in==null)throw new IllegalStateException("Missing planner asset: "+key);BufferedImage result=ImageIO.read(in);if(result==null)throw new IllegalStateException("Empty planner asset: "+key);return result;
        }catch(java.io.IOException error){throw new IllegalStateException(error);}});
        return new Icon(){public int getIconWidth(){return size;}public int getIconHeight(){return size;}public void paintIcon(Component c,Graphics graphics,int x,int y){Graphics2D g=quality(graphics);g.drawImage(image,x,y,size,size,null);g.dispose();}};
    }
    static JLabel label(String text,int size,Color color){JLabel l=new JLabel(text);l.setFont(regular(size));l.setForeground(color);return l;}
    static JLabel heading(String text,int size){JLabel l=label(text,size,INK);l.setFont(bold(size));return l;}
    static void name(JComponent c,String name){c.setName(name);c.getAccessibleContext().setAccessibleName(name);}
    static JButton button(String text,boolean primary,Runnable action){
        JButton b=new JButton(text){@Override protected void paintComponent(Graphics graphics){
            Graphics2D g=quality(graphics);Color fill=getBackground();if(getModel().isPressed())fill=primary?new Color(0x173f76):SURFACE;
            g.setColor(fill);g.fillRoundRect(0,0,getWidth(),getHeight(),12,12);g.dispose();super.paintComponent(graphics);
        }};b.setUI(new BasicButtonUI());b.setFont(medium(12));b.setForeground(primary?Color.WHITE:NAVY);
        b.setBackground(primary?NAVY:Color.WHITE);b.setOpaque(false);b.setContentAreaFilled(false);b.setFocusPainted(false);
        int padding=text.equals("×")||text.matches("\\d{1,2}")?0:12;
        b.setMargin(new Insets(0,0,0,0));b.setBorder(new AbstractBorder(){public Insets getBorderInsets(Component c){int inset=Boolean.TRUE.equals(b.getClientProperty("planner.compact"))?2:padding;return new Insets(0,inset,0,inset);}
            public void paintBorder(Component c,Graphics graphics,int x,int y,int w,int h){Graphics2D g=quality(graphics);
                g.setColor(NAVY.equals(b.getBackground())?NAVY:BORDER);g.drawRoundRect(x,y,w-1,h-1,11,11);g.dispose();}});
        b.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));b.addActionListener(e->action.run());name(b,text);return b;
    }
    static JButton iconButton(String asset,String name,int size,Runnable action){JButton b=button("",false,action);b.setIcon(icon(asset,size));b.setBorder(BorderFactory.createEmptyBorder());name(b,name);b.setToolTipText(name);return b;}
    static JTextField field(String name,String value){JTextField f=new JTextField(value);f.setFont(regular(14));f.setForeground(INK);f.setCaretColor(NAVY);f.setBorder(inputBorder());name(f,name);return f;}
    static Border inputBorder(){return new CompoundBorder(new AbstractBorder(){
        public Insets getBorderInsets(Component c){return new Insets(1,1,1,1);}
        public void paintBorder(Component c,Graphics graphics,int x,int y,int width,int height){Graphics2D g=quality(graphics);g.setColor(BORDER);g.drawRoundRect(x,y,width-1,height-1,11,11);g.dispose();}
    },new EmptyBorder(4,12,4,12));}
    static JCheckBox check(String text){JCheckBox c=new JCheckBox(text);c.setOpaque(false);c.setBorder(BorderFactory.createEmptyBorder());c.setMargin(new Insets(0,0,0,0));c.setFont(medium(12));c.setForeground(INK);c.setIcon(new Icon(){public int getIconWidth(){return 18;}public int getIconHeight(){return 18;}public void paintIcon(Component c,Graphics graphics,int x,int y){Graphics2D g=quality(graphics);g.setColor(Color.WHITE);g.fillRoundRect(x,y,17,17,6,6);g.setColor(BORDER);g.drawRoundRect(x,y,17,17,6,6);g.dispose();}});c.setSelectedIcon(icon("field-check",18));c.setIconTextGap(10);c.setFocusPainted(false);name(c,text);return c;}
    static JCheckBox taskCheck(){JCheckBox c=check("");c.setSelectedIcon(new Icon(){public int getIconWidth(){return 16;}public int getIconHeight(){return 16;}public void paintIcon(Component c,Graphics graphics,int x,int y){Graphics2D g=quality(graphics);g.setColor(NAVY);g.fillRoundRect(x,y,16,16,8,8);icon("task-check",12).paintIcon(c,g,x+2,y+2);g.dispose();}});return c;}
    static <T> JComboBox<T> combo(String name,T[] values){JComboBox<T> c=new JComboBox<>(values);c.setFont(regular(14));c.setForeground(INK);c.setBackground(Color.WHITE);c.setBorder(new LineBorder(BORDER,1,true));name(c,name);
        c.setUI(new PlainComboBoxUI(){@Override protected JButton createArrowButton(){JButton b=new JButton(icon("chevron",14));b.setBorder(new EmptyBorder(0,4,0,8));b.setContentAreaFilled(false);b.setFocusPainted(false);return b;}
            @Override public void paintCurrentValueBackground(Graphics g,Rectangle bounds,boolean focus){g.setColor(Color.WHITE);g.fillRect(bounds.x,bounds.y,bounds.width,bounds.height);}});
        c.setRenderer(new DefaultListCellRenderer(){@Override public Component getListCellRendererComponent(JList<?> list,Object value,int index,boolean selected,boolean focus){JLabel l=(JLabel)super.getListCellRendererComponent(list,value,index,selected,focus);l.setFont(regular(14));l.setBorder(new EmptyBorder(5,10,5,4));l.setBackground(selected?SURFACE:Color.WHITE);l.setForeground(INK);return l;}});return c;
    }
    static class Card extends JPanel {
        private final Color fill;private final int radius;
        private boolean painting,paintInterior;
        Card(Color fill,int radius){this.fill=fill;this.radius=radius;setOpaque(false);}
        private boolean interior(Graphics graphics){
            Rectangle r=graphics.getClipBounds();if(r==null||r.isEmpty())return false;
            int right=r.x+r.width,bottom=r.y+r.height,corner=radius+2;
            return r.x>=2&&r.y>=2&&right<=getWidth()-2&&bottom<=getHeight()-2
                    &&(r.x>=corner&&right<=getWidth()-corner||r.y>=corner&&bottom<=getHeight()-corner);
        }
        private boolean damageIsInterior(Graphics graphics){return painting?paintInterior:interior(graphics);}
        @Override protected void paintComponent(Graphics graphics){super.paintComponent(graphics);Graphics2D g=quality(graphics);g.setColor(fill);if(damageIsInterior(graphics))g.fillRect(0,0,getWidth(),getHeight());else g.fill(new java.awt.geom.RoundRectangle2D.Double(.5,.5,getWidth()-1,getHeight()-1,radius*2,radius*2));g.dispose();}
        @Override protected void paintChildren(Graphics graphics){Graphics2D g=quality(graphics);if(!damageIsInterior(graphics))g.clip(new java.awt.geom.RoundRectangle2D.Double(0,0,getWidth(),getHeight(),radius*2,radius*2));super.paintChildren(g);g.dispose();}
        @Override public void paint(Graphics graphics){boolean previousPainting=painting,previousInterior=paintInterior;painting=true;paintInterior=interior(graphics);try{super.paint(graphics);if(paintInterior)return;Graphics2D g=quality(graphics);g.setColor(BORDER);g.draw(new java.awt.geom.RoundRectangle2D.Double(.5,.5,getWidth()-1,getHeight()-1,radius*2-1,radius*2-1));g.dispose();}finally{painting=previousPainting;paintInterior=previousInterior;}}
    }
    static JScrollPane scroll(Component child){
        JScrollPane s=new dev.synesis.poc.ui.UnifiedScrollPane(child){
            @Override protected JViewport createViewport(){ScrollCacheViewport view=new ScrollCacheViewport();view.setCacheEnabled(true);return view;}
            @Override protected void processMouseWheelEvent(MouseWheelEvent event){
            if(!event.isConsumed()&&isWheelScrollingEnabled()&&getViewport().getViewSize().height<=getViewport().getExtentSize().height){
                Container ancestor=SwingUtilities.getAncestorOfClass(JScrollPane.class,getParent());
                if(ancestor instanceof JScrollPane outer){
                    Point p=SwingUtilities.convertPoint(this,event.getPoint(),outer);
                    outer.dispatchEvent(new MouseWheelEvent(outer,event.getID(),event.getWhen(),event.getModifiersEx(),p.x,p.y,event.getXOnScreen(),event.getYOnScreen(),event.getClickCount(),event.isPopupTrigger(),event.getScrollType(),event.getScrollAmount(),event.getWheelRotation(),event.getPreciseWheelRotation()));
                    event.consume();return;
                }
            }
            super.processMouseWheelEvent(event);
        }};
        s.setBorder(null);s.setBackground(Color.WHITE);s.getViewport().setBackground(Color.WHITE);s.getVerticalScrollBar().setUnitIncrement(dev.synesis.poc.ui.ScrollPolicy.PIXELS_PER_UNIT);s.setHorizontalScrollBarPolicy(ScrollPaneConstants.HORIZONTAL_SCROLLBAR_NEVER);return s;
    }
}
