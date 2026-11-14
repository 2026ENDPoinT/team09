package dev.synesis.poc.ui;

import javax.imageio.ImageIO;
import javax.swing.*;
import javax.swing.plaf.basic.BasicButtonUI;
import java.awt.*;
import java.awt.font.TextAttribute;
import java.awt.font.TextLayout;
import java.awt.image.BufferedImage;
import java.util.Map;
import java.util.function.BooleanSupplier;

/** MAIN-내문서 / 1:3433. Only explicitly enabled destinations have actions. */
public final class LibrarySidebar extends JPanel {
    private static final Color INK=LibraryDesign.INK, MUTED=LibraryDesign.SIDEBAR_SECONDARY;
    private static final Map<String,Icon> ICONS=new java.util.concurrent.ConcurrentHashMap<>();
    private final JComponent account,divider,footer;

    public LibrarySidebar(BooleanSupplier documentsSelected) {
        this(documentsSelected,()->false,null);
    }
    public LibrarySidebar(BooleanSupplier documentsSelected,BooleanSupplier plannerSelected,Runnable openPlanner) {
        this(documentsSelected,plannerSelected,null,openPlanner,null);
    }
    public LibrarySidebar(BooleanSupplier documentsSelected,BooleanSupplier plannerSelected,Runnable openDocuments,Runnable openPlanner,Runnable openProfile) {
        super(null);setBackground(INK);setPreferredSize(new Dimension(170,1));
        Font section=LibraryDesign.medium(12).deriveFont(Map.of(TextAttribute.TRACKING,4f/12f));
        addAt(new TypeLine(16,section,MUTED,"WORKSPACE"),24,24,134,16);
        JButton documents=item("내 문서","documents",documentsSelected);
        connect(documents,openDocuments,"내 문서");
        addAt(documents,12,56,146,44);
        addAt(item("내 메모","notes",()->false),12,108,146,44);
        JPanel extendDivider=new JPanel();extendDivider.setBackground(LibraryDesign.ACTIVE);addAt(extendDivider,12,172,146,1);
        addAt(new TypeLine(16,section,MUTED,"EXTEND"),24,193,134,16);
        Font description=LibraryDesign.medium(10);
        addAt(new TypeLine(16,description,MUTED,"시네시스를"),24,209,134,16);
        addAt(new TypeLine(16,MUTED,new Run(description,"나답게"),new Run(LibraryDesign.font(Font.BOLD,10)," 확장"),new Run(description,"하세요.")),24,225,134,16);
        JButton planner=item("플래너","planner",plannerSelected);
        connect(planner,openPlanner,"플래너");
        addAt(planner,12,253,146,44);
        addAt(item("내 대학생활","campus",()->false),12,305,146,44);
        addAt(item("실험실","labs",()->false),12,357,146,44);

        divider=new JPanel();divider.setBackground(LibraryDesign.ACTIVE);add(divider);
        JButton accountPanel=new JButton();accountPanel.setLayout(null);accountPanel.setUI(new BasicButtonUI());
        accountPanel.setOpaque(false);accountPanel.setContentAreaFilled(false);accountPanel.setBorderPainted(false);accountPanel.setFocusPainted(false);accountPanel.setBorder(null);
        accountPanel.getAccessibleContext().setAccessibleName("내 정보");connect(accountPanel,openProfile,"내 정보");
        JPanel avatar=new JPanel(null){@Override protected void paintComponent(Graphics graphics){Graphics2D g=quality(graphics);g.setColor(LibraryDesign.ACTIVE);g.fillOval(0,0,28,28);g.dispose();}};avatar.setOpaque(false);
        TypeLine initial=new TypeLine(17.5f,LibraryDesign.font(Font.PLAIN,10).deriveFont(10.5f),Color.WHITE,"M");initial.setBounds(9,5,18,18);avatar.add(initial);avatar.setBounds(8,8,28,28);accountPanel.add(avatar);
        TypeLine name=new TypeLine(20,LibraryDesign.medium(13),Color.WHITE,"김민준");name.setBounds(44,3,89,20);accountPanel.add(name);
        TypeLine plan=new TypeLine(16,LibraryDesign.medium(10),MUTED,"Standard Plan");plan.setBounds(44,23,89,16);accountPanel.add(plan);
        account=accountPanel;add(account);
        footer=new TypeLine(16,LibraryDesign.medium(10).deriveFont(9f),MUTED,"Synesis Beta - by C4T(mjKim)");add(footer);
    }
    private void addAt(JComponent c,int x,int y,int w,int h){add(c);c.setBounds(x,y,w,h);}
    private static void connect(JButton button,Runnable action,String tooltip){
        if(action==null)return;
        button.addActionListener(e->action.run());button.setToolTipText(tooltip);button.setFocusable(true);button.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));
    }
    @Override public void doLayout(){divider.setBounds(12,getHeight()-117,133,1);account.setBounds(12,getHeight()-95,133,44);footer.setBounds(20,getHeight()-30,Math.max(1,getWidth()-24),19);}

    private static JButton item(String text,String asset,BooleanSupplier selected) {return new NavButton(text,icon(asset),selected);}
    private static final class NavButton extends JButton implements LibraryMotionClock.Task {
        private final Icon icon;
        private final BooleanSupplier selected;
        private boolean active,over;
        private double hover,activation,fromHover,fromActive;
        private long started;
        private TextLayout textLayout;
        private java.awt.font.FontRenderContext context;
        NavButton(String text,Icon icon,BooleanSupplier selected) {
            super(text);this.icon=icon;this.selected=selected;active=selected.getAsBoolean();activation=active?1:0;
            setUI(new BasicButtonUI());setFont(LibraryDesign.font(Font.PLAIN,13));setForeground(MUTED);
            setOpaque(false);setContentAreaFilled(false);setBorderPainted(false);setFocusPainted(false);setFocusable(false);setBorder(null);
            setRolloverEnabled(true);getAccessibleContext().setAccessibleName(text);setToolTipText("준비 중이에요.");
            getModel().addChangeListener(event->{
                boolean next=getModel().isRollover();if(next!=over){retarget();over=next;begin();}
            });
            addHierarchyListener(event->{if(!isShowing())settle();});
        }
        private void retarget(){fromHover=hover;fromActive=activation;started=System.nanoTime();}
        private void begin(){if(LibraryMotionClock.reduced()||!isShowing()||!LibraryMotionClock.add(this))settle();repaint();}
        private void settle(){LibraryMotionClock.remove(this);hover=over?1:0;activation=selected.getAsBoolean()?1:0;}
        @Override public boolean advance(long now) {
            if(!isShowing()){settle();return false;}
            double t=LibraryMotionClock.ease((now-started)/250_000_000d);
            hover=fromHover+((over?1:0)-fromHover)*t;
            activation=fromActive+((active?1:0)-fromActive)*t;
            repaint();return t<1;
        }
        @Override protected void paintComponent(Graphics graphics) {
            boolean next=selected.getAsBoolean();if(next!=active){retarget();active=next;begin();}
            Graphics2D g=quality(graphics);
            try {
                g.translate(2*hover,0);
                Color background=blend(LibraryDesign.INK,new Color(0x202020),hover);
                background=blend(background,LibraryDesign.ACTIVE,activation);
                if(hover>0||activation>0){g.setColor(background);g.fillRoundRect(0,0,getWidth(),getHeight(),16,16);}
                icon.paintIcon(this,g,12,13);g.setColor(blend(MUTED,Color.WHITE,Math.max(hover,activation)));
                if(textLayout==null||!g.getFontRenderContext().equals(context)) {
                    context=g.getFontRenderContext();textLayout=new TextLayout(getText(),getFont(),context);
                }
                textLayout.draw(g,38,12+(20-textLayout.getAscent()-textLayout.getDescent())/2+textLayout.getAscent());
            } finally {g.dispose();}
        }
        @Override public void removeNotify(){settle();super.removeNotify();}
    }
    private static Color blend(Color a,Color b,double p) {
        return new Color((int)Math.round(a.getRed()+(b.getRed()-a.getRed())*p),
            (int)Math.round(a.getGreen()+(b.getGreen()-a.getGreen())*p),
            (int)Math.round(a.getBlue()+(b.getBlue()-a.getBlue())*p));
    }
    private static Icon icon(String name) {
        return ICONS.computeIfAbsent(name,LibrarySidebar::loadIcon);
    }
    private static Icon loadIcon(String name) {
        final BufferedImage image;
        try(var in=LibrarySidebar.class.getResourceAsStream("/dev/synesis/poc/sidebar/"+name+".png")) {
            if(in==null)throw new IllegalStateException("Missing sidebar icon: "+name);
            image=ImageIO.read(in);
        }catch(java.io.IOException error){throw new IllegalStateException(error);}
        return new DeviceImageIcon(image,18,18);
    }
    private static Graphics2D quality(Graphics graphics){Graphics2D g=(Graphics2D)graphics.create();g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING,RenderingHints.VALUE_TEXT_ANTIALIAS_ON);g.setRenderingHint(RenderingHints.KEY_FRACTIONALMETRICS,RenderingHints.VALUE_FRACTIONALMETRICS_ON);g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BICUBIC);return g;}
    private static float drawLine(Graphics2D g,Font font,String value,float x,float y,float lineHeight){
        TextLayout layout=new TextLayout(value,font,g.getFontRenderContext());
        float baseline=y+(lineHeight-layout.getAscent()-layout.getDescent())/2+layout.getAscent();
        layout.draw(g,x,baseline);return layout.getAdvance();
    }
    private record Run(Font font,String text) {}
    /** Explicit line boxes and font runs preserve Figma's fractional sizes and mixed weights. */
    private static final class TypeLine extends JLabel {
        private final Run[] runs;
        private final float lineHeight;
        private java.awt.font.FontRenderContext context;
        private TextLayout[] layouts;
        TypeLine(float height,Font font,Color color,String text){this(height,color,new Run(font,text));}
        TypeLine(float height,Color color,Run... runs){super(java.util.Arrays.stream(runs).map(Run::text).collect(java.util.stream.Collectors.joining()));this.lineHeight=height;this.runs=runs;setForeground(color);setFont(runs[0].font());setOpaque(false);}
        @Override protected void paintComponent(Graphics graphics){
            Graphics2D g=quality(graphics);
            try {
                if(!g.getFontRenderContext().equals(context)) {
                    context=g.getFontRenderContext();layouts=new TextLayout[runs.length];
                    for(int i=0;i<runs.length;i++)layouts[i]=new TextLayout(runs[i].text(),runs[i].font(),context);
                }
                g.setColor(getForeground());float x=0;
                for(TextLayout layout:layouts){layout.draw(g,x,(lineHeight-layout.getAscent()-layout.getDescent())/2+layout.getAscent());x+=layout.getAdvance();}
            } finally {g.dispose();}
        }
    }
}
