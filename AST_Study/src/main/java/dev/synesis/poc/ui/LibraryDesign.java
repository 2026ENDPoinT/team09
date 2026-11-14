package dev.synesis.poc.ui;

import javax.imageio.ImageIO;
import javax.swing.*;
import javax.swing.border.AbstractBorder;
import javax.swing.border.EmptyBorder;
import javax.swing.plaf.basic.BasicButtonUI;
import java.awt.*;
import java.awt.font.TextAttribute;
import java.awt.image.BufferedImage;
import java.io.IOException;
import java.util.HashMap;
import java.util.Map;

/** Figma design_1 / 3:41 / Desktop 16:9. Scoped to the library, not the study tabs. */
public final class LibraryDesign {
    public static final Color CANVAS=new Color(0xfefefe), INK=new Color(0x141414),
        MUTED=new Color(0x757575), LINE=new Color(0xe0e0e0),
        PREVIEW=new Color(0xf5f8fc), ACTIVE=new Color(0x2c2c2c),
        SIDEBAR_SECONDARY=new Color(0xa6a6a6);
    public static final int SIDEBAR_WIDTH=170;
    private static final int HEADER_HEIGHT=56, ARTWORK_WIDTH=1600, ARTWORK_HEIGHT=56;
    private static final Map<String,BufferedImage> IMAGES=new HashMap<>();
    private static final Map<String,Icon> ICONS=new java.util.LinkedHashMap<>(128,.75f,true) {
        @Override protected boolean removeEldestEntry(Map.Entry<String,Icon> eldest){return size()>256;}
    };
    private static final java.util.concurrent.ConcurrentMap<Integer,Font> FONTS=new java.util.concurrent.ConcurrentHashMap<>();
    private static final Font REGULAR=loadFont("Regular"), MEDIUM=loadFont("Medium"), BOLD=loadFont("Bold"), LIGHT=loadFont("Light");
    private LibraryDesign() {}

    private static Font loadFont(String weight) {
        try(var input=LibraryDesign.class.getResourceAsStream("/dev/synesis/poc/library/NotoSansKR-"+weight+".otf")) {
            if(input==null)throw new IllegalStateException("Missing library font: "+weight);
            return Font.createFont(Font.TRUETYPE_FONT,input);
        }catch(IOException|FontFormatException e){throw new IllegalStateException("Cannot read library font: "+weight,e);}
    }
    public static Font font(int style,int size) {
        Font base=(style&Font.BOLD)!=0?BOLD:REGULAR;
        return size<1||size>128?base.deriveFont((float)size):FONTS.computeIfAbsent(size*4+((style&Font.BOLD)!=0?1:0),key->base.deriveFont((float)size));
    }
    public static Font light(int size){return size<1||size>128?LIGHT.deriveFont((float)size):FONTS.computeIfAbsent(size*4+3,key->LIGHT.deriveFont((float)size));}
    public static Font medium(int size){return size<1||size>128?MEDIUM.deriveFont((float)size):FONTS.computeIfAbsent(size*4+2,key->MEDIUM.deriveFont((float)size));}

    private static synchronized BufferedImage image(String name) {
        return IMAGES.computeIfAbsent(name,key->{
            try(var input=LibraryDesign.class.getResourceAsStream("/dev/synesis/poc/library/"+key+".png")) {
                if(input==null)throw new IllegalStateException("Missing library artwork: "+key);
                BufferedImage image=ImageIO.read(input);
                if(image==null)throw new IllegalStateException("Invalid library artwork: "+key);
                return image;
            } catch(IOException error) {throw new IllegalStateException("Cannot read library artwork: "+key,error);}
        });
    }

    /** Retains Figma's logical slot size while using the exported 3x pixels on Retina. */
    public static synchronized Icon icon(String name,int width,int height) {
        return ICONS.computeIfAbsent(name+":"+width+":"+height,
            key->new DeviceImageIcon(image(name),width,height));
    }

    public static Icon coloredIcon(String name,int width,int height,Color color) {
        String key=name+"-"+Integer.toHexString(color.getRGB());
        BufferedImage source=image(name);
        synchronized(IMAGES) {
            IMAGES.computeIfAbsent(key,unused->{
                BufferedImage tinted=new BufferedImage(source.getWidth(),source.getHeight(),BufferedImage.TYPE_INT_ARGB);
                Graphics2D g=tinted.createGraphics();
                try {g.drawImage(source,0,0,null);g.setComposite(AlphaComposite.SrcIn);g.setColor(color);g.fillRect(0,0,tinted.getWidth(),tinted.getHeight());}
                finally{g.dispose();}
                return tinted;
            });
        }
        return icon(key,width,height);
    }

    public static void button(AbstractButton button,boolean primary) {
        button.setUI(new BasicButtonUI());
        button.setFont(medium(14));
        button.setForeground(primary?Color.WHITE:INK);
        button.setBackground(primary?INK:Color.WHITE);
        button.setOpaque(false);button.setContentAreaFilled(false);
        button.setFocusPainted(false);button.setRolloverEnabled(true);
        button.setBorder(new RoundedBorder(8,primary?INK:LINE,new Insets(0,16,0,16)) {
            @Override public void paintBorder(Component c,Graphics graphics,int x,int y,int w,int h) {
                Graphics2D g=(Graphics2D)graphics.create();
                try {
                    g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                    Color fill=button.getBackground();
                    if(button.getModel().isPressed())fill=primary?ACTIVE:new Color(0xededed);
                    else if(button.getModel().isRollover())fill=primary?ACTIVE:new Color(0xf6f6f6);
                    g.setColor(fill);g.fillRoundRect(x,y,w-1,h-1,16,16);
                    g.setColor(primary?INK:LINE);
                    g.drawRoundRect(x,y,w-1,h-1,16,16);
                } finally {g.dispose();}
            }
        });
        // Swing paints the border after the text. Paint our fill first instead.
        button.setUI(new BasicButtonUI() {
            @Override public void paint(Graphics graphics,JComponent component) {
                button.getBorder().paintBorder(button,graphics,0,0,button.getWidth(),button.getHeight());
                super.paint(graphics,component);
            }
        });
        button.setBorderPainted(false);
        button.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));
    }

    public static class RoundedBorder extends AbstractBorder {
        private final int radius;
        private final Color color;
        private final Insets insets;
        public RoundedBorder(int radius,Color color,Insets insets){this.radius=radius;this.color=color;this.insets=insets;}
        @Override public Insets getBorderInsets(Component c){return (Insets)insets.clone();}
        @Override public Insets getBorderInsets(Component c,Insets target){target.set(insets.top,insets.left,insets.bottom,insets.right);return target;}
        @Override public void paintBorder(Component c,Graphics graphics,int x,int y,int w,int h){
            Graphics2D g=(Graphics2D)graphics.create();
            try {g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                g.setColor(color);g.drawRoundRect(x,y,w-1,h-1,radius*2,radius*2);
            }finally{g.dispose();}
        }
    }

    public static JPanel searchField(JTextField field) {
        JPanel panel=new JPanel(new BorderLayout(12,0));panel.setBackground(Color.WHITE);
        panel.setBorder(new RoundedBorder(8,LINE,new Insets(1,17,1,12)));
        panel.setPreferredSize(new Dimension(500,48));
        panel.add(new JLabel(icon("search",20,20)),BorderLayout.WEST);
        field.setBorder(new EmptyBorder(0,0,0,0));field.setOpaque(false);
        field.setFont(font(Font.PLAIN,14));field.setForeground(INK);
        field.setToolTipText("자료 이름으로 검색해 보세요");
        field.getAccessibleContext().setAccessibleName("자료 이름 검색");
        JLayer<JTextField> entry=new JLayer<>(field,new javax.swing.plaf.LayerUI<>() {
            @Override public void paint(Graphics graphics,JComponent c){
                super.paint(graphics,c);
                if(field.getText().isEmpty()&&!field.hasFocus()){
                    graphics.setFont(field.getFont());graphics.setColor(MUTED);
                    FontMetrics fm=graphics.getFontMetrics();
                    graphics.drawString("자료 이름으로 검색해 보세요",0,(c.getHeight()-fm.getHeight())/2+fm.getAscent());
                }
            }
        });
        panel.add(entry,BorderLayout.CENTER);
        field.addFocusListener(new java.awt.event.FocusAdapter(){
            public void focusGained(java.awt.event.FocusEvent e){entry.repaint();}
            public void focusLost(java.awt.event.FocusEvent e){entry.repaint();}
        });
        JLabel shortcut=new JLabel(System.getProperty("os.name","").toLowerCase().contains("mac")?"⌘ K":"⌃ K",SwingConstants.CENTER);
        shortcut.setFont(medium(10));shortcut.setForeground(MUTED);
        JPanel shortcutBox=new JPanel(new GridBagLayout());shortcutBox.setOpaque(false);
        StudyTheme.RoundedPanel key=new StudyTheme.RoundedPanel(new BorderLayout(),8,new Color(0xf6f6f6),null);
        key.setPreferredSize(new Dimension(30,24));key.add(shortcut);shortcutBox.add(key);
        panel.add(shortcutBox,BorderLayout.EAST);
        int mask=System.getProperty("os.name","").toLowerCase().contains("mac")?java.awt.event.InputEvent.META_DOWN_MASK:java.awt.event.InputEvent.CTRL_DOWN_MASK;
        panel.getInputMap(JComponent.WHEN_IN_FOCUSED_WINDOW).put(KeyStroke.getKeyStroke(java.awt.event.KeyEvent.VK_K,mask),"search");
        panel.getActionMap().put("search",new AbstractAction(){public void actionPerformed(java.awt.event.ActionEvent e){field.requestFocusInWindow();}});
        return panel;
    }

    public static JComponent viewSwitch(java.util.function.Consumer<Boolean> changed) {
        JPanel panel=new JPanel(new FlowLayout(FlowLayout.LEFT,2,2));panel.setOpaque(false);
        panel.setBorder(new RoundedBorder(6,LINE,new Insets(0,3,0,3)));
        panel.setPreferredSize(new Dimension(68,32));
        ButtonGroup group=new ButtonGroup();
        for(boolean list:new boolean[]{false,true}){
            String label=list?"목록 보기":"격자 보기";
            JToggleButton button=new JToggleButton(icon(list?"list":"grid",16,16));
            button.setToolTipText(label);button.getAccessibleContext().setAccessibleName(label);
            button.setPreferredSize(new Dimension(28,26));button.setBorder(new EmptyBorder(0,0,0,0));
            button.setOpaque(false);button.setContentAreaFilled(false);button.setBorderPainted(false);button.setFocusPainted(false);
            button.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));button.setSelected(!list);
            button.setUI(new BasicButtonUI(){@Override public void paint(Graphics graphics,JComponent component){
                if(button.isSelected()||button.getModel().isRollover()){
                    Graphics2D g=(Graphics2D)graphics.create();try{g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                        g.setColor(button.isSelected()?new Color(0xededed):new Color(0xf6f6f6));g.fillRoundRect(0,0,component.getWidth(),component.getHeight(),8,8);
                    }finally{g.dispose();}
                }super.paint(graphics,component);
            }});
            button.addActionListener(event->{if(button.isSelected())changed.accept(list);});group.add(button);panel.add(button);
        }
        panel.getAccessibleContext().setAccessibleName("자료 보기 방식");
        return panel;
    }

    public static JPanel header(Runnable profile) {
        return new GlassHeader(profile);
    }

    private static final class GlassHeader extends JPanel {
        private final JLabel logo=new JLabel("SYNESIS",SwingConstants.CENTER);
        private final JLabel identity=new JLabel("Lecture Studio");
        private final JPanel beta=new StudyTheme.RoundedPanel(new GridBagLayout(),8,new Color(0xededed),null);
        private final JPanel saved=new JPanel(new FlowLayout(FlowLayout.LEFT,8,0));
        private final JLabel help=new JLabel(icon("help",20,20));
        private final JButton account=new JButton("M");
        GlassHeader(Runnable profile){
            super(null);setOpaque(true);setBackground(Color.WHITE);
            setPreferredSize(new Dimension(1600,HEADER_HEIGHT));
            logo.getAccessibleContext().setAccessibleName("SYNESIS");
            logo.setForeground(INK);logo.setFont(font(Font.BOLD,22).deriveFont(Map.of(TextAttribute.TRACKING,-.8f/22)));
            identity.setFont(font(Font.PLAIN,14));identity.setForeground(new Color(0x555555));
            JLabel badge=new JLabel("BETA");badge.setFont(medium(10));badge.setForeground(new Color(0x555555));beta.add(badge);
            saved.setOpaque(false);JLabel check=new JLabel("✓");check.setForeground(MUTED);check.setFont(font(Font.PLAIN,16));saved.add(check);
            JLabel status=new JLabel("최신 버전입니다. v0.0.1");status.setForeground(MUTED);status.setFont(font(Font.PLAIN,12));saved.add(status);
            saved.setToolTipText("현재 앱 버전: v0.0.1");
            help.setToolTipText("도움말 · 준비 중이에요");
            account.setUI(new BasicButtonUI());account.setOpaque(false);account.setContentAreaFilled(false);
            account.setBorderPainted(false);account.setFocusPainted(false);account.setMargin(new Insets(0,0,0,0));
            account.setForeground(Color.WHITE);account.setFont(medium(14));
            account.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));account.setToolTipText("내 정보");
            account.addActionListener(e->profile.run());
            add(logo);add(identity);add(beta);add(saved);add(help);add(account);
        }
        @Override public void doLayout(){
            int center=HEADER_HEIGHT/2;
            logo.setBounds(0,0,157,HEADER_HEIGHT);identity.setBounds(181,center-11,108,22);beta.setBounds(301,center-11,40,22);
            int right=getWidth()-32;
            account.setBounds(right-34,center-17,34,34);help.setBounds(right-78,center-10,20,20);
            saved.setVisible(getWidth()>=1000);saved.setBounds(right-312,center-12,210,24);
        }
        @Override protected void paintComponent(Graphics graphics){
            super.paintComponent(graphics);
            Graphics2D g=(Graphics2D)graphics.create();
            try {
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                g.setColor(Color.BLACK);
                g.fill(new java.awt.geom.Rectangle2D.Double(0,HEADER_HEIGHT-0.8,getWidth(),0.8));
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                Rectangle bounds=account.getBounds();g.setColor(INK);g.fillOval(bounds.x,bounds.y,bounds.width,bounds.height);
            }finally{g.dispose();}
        }
    }
}
