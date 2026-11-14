package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.DeviceImageIcon;
import dev.synesis.poc.ui.LibraryDesign;
import javax.imageio.ImageIO;
import javax.swing.*;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.util.LinkedHashMap;
import java.util.Map;

/** Figma 41:3271 shelf objects; stored folder appearance and live PDF previews remain data. */
final class LibraryShelfDesign {
    static final int HEIGHT=260,ART_HEIGHT=186;
    private static final Map<String,BufferedImage> IMAGES=new LinkedHashMap<>();
    private static final Map<Integer,Icon> FOLDERS=new LinkedHashMap<>(32,.75f,true){
        @Override protected boolean removeEldestEntry(Map.Entry<Integer,Icon> e){return size()>48;}
    };
    private static BufferedImage image(String name){return IMAGES.computeIfAbsent(name,key->{
        try(var in=LibraryShelfDesign.class.getResourceAsStream("/dev/synesis/poc/library/redesign/"+key+".png")){
            if(in==null)throw new IllegalStateException("Missing shelf asset: "+key);
            BufferedImage result=ImageIO.read(in);if(result==null)throw new IllegalStateException("Invalid shelf asset: "+key);return result;
        }catch(java.io.IOException e){throw new IllegalStateException(e);}
    });}
    private static boolean darkFolder(Color color){
        float[] hsb=Color.RGBtoHSB(color.getRed(),color.getGreen(),color.getBlue(),null);
        return hsb[1]<.18f&&hsb[2]<.30f;
    }
    static Color folderGlyphColor(Color color){return darkFolder(color)?new Color(0xb1b5bd):color.darker();}
    static Icon folder(Color color,Icon glyph){
        Icon base=FOLDERS.computeIfAbsent(color.getRGB(),key->{
            BufferedImage art=new BufferedImage(594,474,BufferedImage.TYPE_INT_ARGB);
            Graphics2D g=art.createGraphics();
            try {
                g.scale(3,3);
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                float[] hsb=Color.RGBtoHSB(color.getRed(),color.getGreen(),color.getBlue(),null);
                // Dark choices must keep their luminance, even when charcoal has a slight cool tint.
                Color pigment=hsb[1]<.08f||hsb[2]<.30f?color:Color.getHSBColor(hsb[0],Math.max(.86f,hsb[1]),Math.max(.88f,hsb[2]));
                boolean dark=darkFolder(color);
                Color deep=dark?blend(pigment,Color.BLACK,.28f):blend(pigment,new Color(0x101828),.30f);
                for(int i=5;i>=1;i--){
                    g.setColor(new Color(14,24,42,5));
                    g.fillRoundRect(12-i,43+i,174+i*2,99,18,18);
                }
                java.awt.geom.Path2D back=new java.awt.geom.Path2D.Double();
                back.moveTo(10,33);back.quadTo(10,21,22,21);
                back.lineTo(65,21);back.quadTo(70,21,74,25);back.lineTo(86,37);
                back.lineTo(177,37);back.quadTo(188,37,188,48);
                back.lineTo(188,130);back.quadTo(188,141,177,141);
                back.lineTo(22,141);back.quadTo(10,141,10,129);back.closePath();
                g.setPaint(new GradientPaint(10,21,deep,188,141,pigment));g.fill(back);
                // A visible inner lip separates the folder tab from its forward-facing pocket.
                g.setColor(blend(pigment,Color.BLACK,.38f));g.fillRoundRect(20,40,158,31,8,8);
                g.setColor(new Color(255,255,255,185));g.fillRoundRect(25,44,148,18,4,4);
                java.awt.geom.Path2D front=new java.awt.geom.Path2D.Double();
                front.moveTo(21,52);front.lineTo(179,45);front.quadTo(190,44,189,56);
                front.lineTo(183,131);front.quadTo(182,141,171,141);
                front.lineTo(23,141);front.quadTo(12,141,12,130);
                front.lineTo(10,64);front.quadTo(10,53,21,52);front.closePath();
                g.setPaint(new LinearGradientPaint(16,48,180,143,new float[]{0f,.55f,1f},
                    new Color[]{dark?blend(pigment,Color.WHITE,.14f):pigment,
                        dark?blend(pigment,Color.WHITE,.025f):blend(pigment,Color.BLACK,.04f),blend(pigment,Color.BLACK,.20f)}));
                g.fill(front);
                Graphics2D gloss=(Graphics2D)g.create();
                try {
                    gloss.clip(front);
                    java.awt.geom.Path2D reflection=new java.awt.geom.Path2D.Double();
                    reflection.moveTo(5,53);reflection.lineTo(193,44);reflection.lineTo(193,76);
                    reflection.curveTo(132,94,75,65,5,84);reflection.closePath();
                    gloss.setPaint(new GradientPaint(0,48,dark?new Color(255,255,255,22):new Color(12,22,40,8),0,90,dark?new Color(255,255,255,2):new Color(12,22,40,43)));
                    gloss.fill(reflection);
                } finally {gloss.dispose();}
                g.setStroke(new BasicStroke(.9f));g.setColor(dark?new Color(139,148,160,105):new Color(deep.getRed(),deep.getGreen(),deep.getBlue(),135));g.draw(front);
                // Small debossed index marks replace the old white sticker and decorative strokes.
                g.setStroke(new BasicStroke(2.4f,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));
                g.setColor(dark?new Color(169,178,190,155):new Color(15,25,40,95));g.drawLine(28,115,53,115);
                g.setStroke(new BasicStroke(1.5f,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));
                g.setColor(dark?new Color(169,178,190,100):new Color(15,25,40,60));g.drawLine(28,122,67,122);
            } finally {g.dispose();}
            return new DeviceImageIcon(art,198,158);
        });
        if(glyph==null)return base;
        return new Icon(){public int getIconWidth(){return 198;}public int getIconHeight(){return 158;}
            public void paintIcon(Component c,Graphics graphics,int x,int y){base.paintIcon(c,graphics,x,y);glyph.paintIcon(c,graphics,x+182-glyph.getIconWidth(),y+88-glyph.getIconHeight()/2);}};
    }
    private static final class TrashArtwork {
        static final float WIDTH_SCALE=.81f;
        static final BufferedImage IMAGE=createTrashArtwork();
        static final Icon ICON=new DeviceImageIcon(IMAGE,Math.round(198*WIDTH_SCALE),158);
        static final Map<Integer,Icon> SMALL=new LinkedHashMap<>(8,.75f,true){
            @Override protected boolean removeEldestEntry(Map.Entry<Integer,Icon> entry){return size()>8;}
        };
    }
    static Icon trash(){return TrashArtwork.ICON;}
    static Icon trash(int size){
        int width=Math.max(1,size);
        return TrashArtwork.SMALL.computeIfAbsent(width,key->new DeviceImageIcon(TrashArtwork.IMAGE,Math.max(1,Math.round(key*TrashArtwork.WIDTH_SCALE)),Math.max(1,Math.round(key*158f/198))));
    }
    private static BufferedImage createTrashArtwork(){
        BufferedImage art=new BufferedImage(594,474,BufferedImage.TYPE_INT_ARGB);
        Graphics2D g=art.createGraphics();
        try{
            g.scale(3,3);g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
            g.translate(9.9,0);g.scale(.9,1); // Compress the cached artwork horizontally around its center.
            Color teal=new Color(0x167d82),deep=new Color(0x0a4d54),light=new Color(0x58a7aa);
            for(int spread=5;spread>=1;spread--){g.setColor(new Color(5,40,45,6));g.fillOval(43-spread,137-spread/2,112+2*spread,9+spread);}
            java.awt.geom.Area handle=new java.awt.geom.Area(new java.awt.geom.RoundRectangle2D.Double(75,19,48,25,12,12));
            handle.subtract(new java.awt.geom.Area(new java.awt.geom.RoundRectangle2D.Double(85,26,28,13,5,5)));
            g.setPaint(new GradientPaint(75,19,light,123,44,deep));g.fill(handle);
            java.awt.geom.Path2D body=new java.awt.geom.Path2D.Double();
            body.moveTo(38,49);body.lineTo(160,49);body.lineTo(151,129);
            body.quadTo(150,141,137,141);body.lineTo(61,141);body.quadTo(48,141,47,129);body.closePath();
            g.setPaint(new LinearGradientPaint(40,55,160,137,new float[]{0,.48f,1},new Color[]{light,teal,deep}));g.fill(body);
            Graphics2D gloss=(Graphics2D)g.create();
            try{
                gloss.clip(body);
                java.awt.geom.Path2D shine=new java.awt.geom.Path2D.Double();shine.moveTo(32,51);shine.lineTo(166,51);shine.lineTo(166,81);
                shine.curveTo(119,96,70,64,32,83);shine.closePath();
                gloss.setPaint(new GradientPaint(0,51,new Color(255,255,255,90),0,90,new Color(255,255,255,5)));gloss.fill(shine);
                gloss.setPaint(new GradientPaint(133,0,new Color(5,54,62,0),158,0,new Color(5,54,62,90)));gloss.fillRect(130,49,35,95);
            }finally{gloss.dispose();}
            g.setStroke(new BasicStroke(.9f));g.setColor(new Color(7,65,72,150));g.draw(body);
            g.setStroke(new BasicStroke(5.5f,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));
            for(int x:new int[]{75,99,123}){
                g.setColor(new Color(255,255,255,90));g.drawLine(x-1,80,x-1,119);
                g.setColor(new Color(6,61,68,110));g.drawLine(x,79,x,118);
            }
            g.setPaint(new GradientPaint(25,36,new Color(0x63b2b4),173,55,new Color(0x14676f)));
            g.fillRoundRect(24,36,150,21,9,9);
            g.setColor(new Color(255,255,255,155));g.setStroke(new BasicStroke(1.5f,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));g.drawLine(32,39,165,39);
            g.setColor(new Color(7,62,69,145));g.setStroke(new BasicStroke(1.1f));g.drawRoundRect(24,36,150,21,9,9);
            g.setColor(new Color(5,47,54,80));g.fillRoundRect(38,55,122,5,3,3);
        }finally{g.dispose();}
        return art;
    }
    private static Color blend(Color a,Color b,float amount){float t=Math.max(0,Math.min(1,amount));return new Color(Math.round(a.getRed()*(1-t)+b.getRed()*t),Math.round(a.getGreen()*(1-t)+b.getGreen()*t),Math.round(a.getBlue()*(1-t)+b.getBlue()*t));}
    static void menu(JButton button){
        button.setIcon(new DeviceImageIcon(image("ellipsis"),18,18));LibraryDesign.button(button,false);
        button.setMargin(new Insets(0,0,0,0));button.setBorder(new LibraryDesign.RoundedBorder(8,LibraryDesign.LINE,new Insets(0,0,0,0)));
        button.setPreferredSize(new Dimension(28,28));button.getAccessibleContext().setAccessibleName(button.getToolTipText());
    }
    static void popup(JPopupMenu popup){
        popup.setBackground(Color.WHITE);
        popup.addSeparator();JMenuItem close=new JMenuItem("닫기");close.addActionListener(e->popup.setVisible(false));popup.add(close);
        for(Component component:popup.getComponents())if(component instanceof JMenuItem item){
            item.setBackground(Color.WHITE);item.setFont(LibraryDesign.font(Font.PLAIN,12));item.setForeground(item.getText().contains("삭제")?new Color(0xc22b2b):LibraryDesign.INK);
            item.setPreferredSize(new Dimension(180,34));item.setMargin(new Insets(0,12,0,12));
        }
    }
    static JPanel content(JComponent art,String name,JButton menu,JLabel metadata,String date){
        JLabel title=new JLabel(name,SwingConstants.CENTER){@Override protected void paintComponent(Graphics graphics){
            Graphics2D g=(Graphics2D)graphics.create();g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING,RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
            g.setFont(getFont());g.setColor(getForeground());FontMetrics fm=g.getFontMetrics();String shown=getText();int max=Math.max(1,getWidth()-56);
            if(fm.stringWidth(shown)>max){while(!shown.isEmpty()&&fm.stringWidth(shown+"…")>max)shown=shown.substring(0,shown.offsetByCodePoints(shown.length(),-1));shown+="…";}
            g.drawString(shown,(getWidth()-fm.stringWidth(shown))/2,(getHeight()-fm.getHeight())/2+fm.getAscent());g.dispose();
        }};
        title.setFont(LibraryDesign.medium(15));title.setForeground(LibraryDesign.INK);title.setToolTipText(name);
        metadata.setFont(LibraryDesign.font(Font.PLAIN,12));metadata.setForeground(LibraryDesign.MUTED);metadata.setHorizontalAlignment(SwingConstants.CENTER);
        JLabel modified=new JLabel(date,SwingConstants.CENTER);modified.setFont(LibraryDesign.font(Font.PLAIN,12));modified.setForeground(LibraryDesign.MUTED);
        JComponent animatedArt=dev.synesis.poc.ui.LibraryItemMotion.artwork(art);
        JPanel body=new JPanel(null){@Override public void doLayout(){
            int width=Math.min(198,getWidth()),left=(getWidth()-width)/2;
            animatedArt.setBounds(0,0,getWidth(),ART_HEIGHT);title.setBounds(left,ART_HEIGHT,width,28);menu.setBounds(left+width-28,ART_HEIGHT,28,28);
            metadata.setBounds(left,ART_HEIGHT+32,width,18);modified.setBounds(left,ART_HEIGHT+54,width,18);
        }};
        body.setOpaque(false);body.add(animatedArt);body.add(title);body.add(menu);body.setComponentZOrder(menu,0);body.add(metadata);body.add(modified);return body;
    }
    static JLabel artwork(Icon icon){JLabel label=new JLabel(icon,SwingConstants.CENTER);label.setVerticalAlignment(SwingConstants.CENTER);return label;}
    static final class PaperCover extends JLabel {
        private final Icon corner=new DeviceImageIcon(image("paper-corner"),17,17);
        private Image previewSource;
        private Icon preview;
        PaperCover(){super("PDF",SwingConstants.CENTER);setPreferredSize(new Dimension(198,186));}
        @Override protected void paintComponent(Graphics graphics){
            Graphics2D g=(Graphics2D)graphics.create();g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
            if(getIcon() instanceof ImageIcon icon&&icon.getIconWidth()>0&&icon.getIconHeight()>0){
                int availableWidth=Math.max(1,getWidth()-14),availableHeight=Math.max(1,getHeight()-16);
                double scale=Math.min(availableWidth/(double)icon.getIconWidth(),availableHeight/(double)icon.getIconHeight());
                int w=Math.max(1,(int)Math.round(icon.getIconWidth()*scale)),h=Math.max(1,(int)Math.round(icon.getIconHeight()*scale));
                int x=(getWidth()-w)/2,y=(getHeight()-h)/2-2;
                for(int spread=5;spread>=1;spread--){g.setColor(new Color(10,18,31,4));g.fillRoundRect(x-spread/2,y+3,w+spread,h+spread,8,8);}
                g.setColor(Color.WHITE);g.fillRoundRect(x-2,y-2,w+4,h+4,8,8);
                if(icon.getImage() instanceof BufferedImage pixels){
                    if(previewSource!=pixels||preview==null||preview.getIconWidth()!=w||preview.getIconHeight()!=h){
                        previewSource=pixels;preview=DeviceImageIcon.thumbnail(pixels,w,h);
                    }
                    preview.paintIcon(this,g,x,y);
                }else{
                    g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BICUBIC);
                    g.drawImage(icon.getImage(),x,y,w,h,null);
                }
                g.setColor(LibraryDesign.LINE);g.drawRoundRect(x-2,y-2,w+3,h+3,8,8);
                g.dispose();return;
            }
            int x=(getWidth()-133)/2,y=(getHeight()-174)/2-2;
            for(int spread=6;spread>=1;spread--){g.setColor(new Color(10,18,31,3));g.fillRoundRect(x-spread/2,y+3,133+spread,174+spread,10,10);}
            g.setColor(Color.WHITE);g.fillRoundRect(x,y,133,174,10,10);g.setColor(LibraryDesign.LINE);g.drawRoundRect(x,y,132,173,10,10);
            g.setColor(LibraryDesign.INK);g.fillRect(x+13,y+18,107,3);
            g.setFont(LibraryDesign.font(Font.BOLD,12));g.setColor(LibraryDesign.MUTED);g.drawString("PDF",x+13,y+47);
            corner.paintIcon(this,g,x+115,y-1);g.dispose();
        }
    }
}
