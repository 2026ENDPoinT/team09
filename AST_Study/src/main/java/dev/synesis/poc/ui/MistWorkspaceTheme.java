package dev.synesis.poc.ui;

import javax.imageio.ImageIO;
import javax.swing.*;
import javax.swing.border.EmptyBorder;
import javax.swing.plaf.basic.BasicButtonUI;
import java.awt.*;
import java.awt.geom.RoundRectangle2D;
import java.awt.geom.Area;
import java.awt.image.BufferedImage;
import javax.swing.plaf.LayerUI;
import java.util.ArrayList;
import java.util.List;
import java.util.HashMap;
import java.util.Map;

/** Figma design_1 / 53:184. Study chrome only; summary/concept prose keeps its renderer. */
public final class MistWorkspaceTheme {
    public static final String SOFT_HEX="#f5f9ff";
    public static final Color PAPER=Color.WHITE, SOFT=Color.decode(SOFT_HEX), HEADER=new Color(0xf9fcff),
        LINE=new Color(0xd4e2f4), INNER_LINE=new Color(0xdfe9f7), TEXT=new Color(0x45474c),
        MUTED=new Color(0x61656c), INK=new Color(0x141414), SHADOW=new Color(0x2d3a4f);
    private static final Map<String,BufferedImage> IMAGES=new HashMap<>();
    private static final Map<String,BufferedImage> SHADOW_PATCHES=new HashMap<>();
    private static final Map<String,Icon> ICONS=new java.util.LinkedHashMap<>(64,.75f,true) {
        @Override protected boolean removeEldestEntry(Map.Entry<String,Icon> eldest){return size()>128;}
    };
    private MistWorkspaceTheme() {}
    public static Font font(int style,int size){return LibraryDesign.font(style,size);}
    public static synchronized Icon icon(String name,int size){return ICONS.computeIfAbsent(name+":"+size,key->createIcon(name,size));}
    private static Icon createIcon(String name,int size){
        if("microphone".equals(name))return new Icon(){
            public int getIconWidth(){return size;}
            public int getIconHeight(){return size;}
            public void paintIcon(Component c,Graphics graphics,int x,int y){
                Graphics2D g=(Graphics2D)graphics.create();
                try{
                    g.translate(x,y);g.scale(size/20.0,size/20.0);
                    g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                    g.setStroke(new BasicStroke(1.5f,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));
                    g.setColor(c.isEnabled()?c.getForeground():MUTED);
                    g.drawRoundRect(7,1,6,11,6,6);g.drawArc(4,5,12,11,180,180);
                    g.drawLine(10,16,10,19);g.drawLine(6,19,14,19);
                }finally{g.dispose();}
            }
        };
        if("page-index".equals(name))return new Icon(){
            public int getIconWidth(){return size;}
            public int getIconHeight(){return size;}
            public void paintIcon(Component c,Graphics graphics,int x,int y){
                Graphics2D g=(Graphics2D)graphics.create();
                try{
                    g.translate(x,y);g.scale(size/20.0,size/20.0);
                    g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                    g.setStroke(new BasicStroke(1.3f,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));
                    g.setColor(c.isEnabled()?c.getForeground():MUTED);
                    for(int row=0;row<3;row++){
                        int top=2+row*6;
                        g.drawRoundRect(2,top,5,4,1,1);
                        g.drawLine(10,top+1,18,top+1);g.drawLine(10,top+3,15,top+3);
                    }
                }finally{g.dispose();}
            }
        };
        BufferedImage image;
        synchronized(IMAGES){image=IMAGES.computeIfAbsent(name,key->{
            try(var stream=MistWorkspaceTheme.class.getResourceAsStream("/dev/synesis/poc/mist/"+key+".png")){
                if(stream==null)throw new IllegalStateException("Missing Mist navy icon: "+key);
                BufferedImage loaded=ImageIO.read(stream);
                if(loaded==null)throw new IllegalStateException("Invalid Mist navy icon: "+key);
                return loaded;
            }catch(java.io.IOException e){throw new IllegalStateException(e);}
        });}
        return new DeviceImageIcon(image,size,size);
    }
    public static void button(AbstractButton button,boolean outlined){
        button.putClientProperty("synesis.preserveButton",true);button.putClientProperty("synesis.preserveFont",true);
        button.setFont(font(Font.PLAIN,12));button.setForeground(new Color(0x252629));button.setBackground(PAPER);
        button.setOpaque(false);button.setContentAreaFilled(false);button.setBorderPainted(false);button.setFocusPainted(false);
        button.setBorder(new EmptyBorder(0,12,0,12));button.setIconTextGap(6);
        button.setPreferredSize(new Dimension(Math.max(32,button.getPreferredSize().width),32));
        button.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));
        button.setUI(new BasicButtonUI(){
            public void paint(Graphics graphics,JComponent component){
                Graphics2D g=(Graphics2D)graphics.create();
                try{
                    g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                    if(outlined||button.getModel().isRollover()||button.isSelected()||Boolean.TRUE.equals(button.getClientProperty("mist.whiteButton"))){
                        g.setColor(button.getModel().isRollover()||button.isSelected()?SOFT:button.getBackground());
                        g.fillRoundRect(0,0,component.getWidth()-1,component.getHeight()-1,16,16);
                    }
                    if(outlined){
                        g.setColor(LINE);g.drawRoundRect(0,0,component.getWidth()-1,component.getHeight()-1,16,16);
                    }
                }finally{g.dispose();}
                super.paint(graphics,component);
            }
        });
    }
    public static JButton iconButton(String name,String tooltip,int size){
        JButton button=new JButton(icon(name,size));button(button,false);button.setBorder(new EmptyBorder(0,0,0,0));
        button.putClientProperty("mist.whiteButton",true);
        button.setPreferredSize(new Dimension(32,32));button.setToolTipText(tooltip);button.getAccessibleContext().setAccessibleName(tooltip);return button;
    }
    public static JPanel heading(int left){
        JPanel panel=new JPanel(new BorderLayout(8,0));panel.setBackground(HEADER);
        panel.setBorder(BorderFactory.createCompoundBorder(BorderFactory.createMatteBorder(0,0,1,0,LINE),new EmptyBorder(0,left,0,16)));
        panel.setPreferredSize(new Dimension(1,42));return panel;
    }
    public static JLabel label(String text,int size,Color color,int style){
        JLabel label=new JLabel(text);label.setFont(font(style,size));label.setForeground(color);return label;
    }
    public static JLabel badge(String text){
        JLabel label=new JLabel(text){@Override protected void paintComponent(Graphics graphics){
            Graphics2D g=(Graphics2D)graphics.create();try{g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);g.setColor(SOFT);g.fillRoundRect(0,0,getWidth(),getHeight(),12,12);}finally{g.dispose();}super.paintComponent(graphics);
        }};
        label.setFont(font(Font.PLAIN,10));label.setForeground(MUTED);label.setOpaque(false);return label;
    }
    public static void comboBox(JComboBox<?> box,boolean outlined){
        box.setFont(font(Font.PLAIN,12));box.setForeground(TEXT);box.setBackground(outlined?PAPER:SOFT);
        box.putClientProperty("synesis.preserveFont",true);box.setOpaque(false);box.setBorder(new EmptyBorder(0,8,0,0));
        box.setUI(new PlainComboBoxUI(){
            @Override protected JButton createArrowButton(){
                JButton arrow=iconButton("chevron","선택",12);arrow.putClientProperty("mist.whiteButton",false);return arrow;
            }
            @Override public void paintCurrentValueBackground(Graphics g,Rectangle b,boolean focused){}
            // The closed renderer is transparent. Native focus selection colors
            // can otherwise paint white text without its dark selection background.
            @Override public void paintCurrentValue(Graphics g,Rectangle b,boolean focused){
                super.paintCurrentValue(g,b,false);
            }
            @Override public void paint(Graphics graphics,JComponent c){
                Graphics2D g=(Graphics2D)graphics.create();
                try{g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);g.setColor(box.getBackground());g.fillRoundRect(0,0,c.getWidth()-1,c.getHeight()-1,16,16);if(outlined){g.setColor(LINE);g.drawRoundRect(0,0,c.getWidth()-1,c.getHeight()-1,16,16);}}finally{g.dispose();}
                super.paint(graphics,c);
            }
        });
        box.setRenderer(new DefaultListCellRenderer(){@Override public Component getListCellRendererComponent(JList<?> list,Object value,int index,boolean selected,boolean focused){
            JLabel label=(JLabel)super.getListCellRendererComponent(list,value,index,selected,focused);
            label.setFont(font(Font.PLAIN,12));label.setForeground(TEXT);label.setBorder(new EmptyBorder(2,0,2,0));label.setOpaque(index>=0);if(index>=0)label.setBackground(selected?SOFT:PAPER);return label;
        }});
    }
    /** Paint outside rounded panes without adding layout insets to the Figma measurements. */
    public static JLayer<JComponent> shadows(JComponent content){
        return new JLayer<>(content,new LayerUI<>(){
            @Override public void paint(Graphics graphics,JComponent layer){
                super.paint(graphics,layer);
                Rectangle damage=graphics.getClipBounds();
                if(damage==null)damage=new Rectangle(0,0,layer.getWidth(),layer.getHeight());
                List<JComponent> surfaces=new ArrayList<>();collect(content,surfaces,layer,damage);
                Graphics2D g=(Graphics2D)graphics.create();
                try{
                    g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                    for(JComponent surface:surfaces){
                        if(!surface.isVisible()||surface.getWidth()<=0||surface.getHeight()<=0)continue;
                        Rectangle b=SwingUtilities.convertRectangle(surface.getParent(),surface.getBounds(),layer);
                        Rectangle extent=new Rectangle(b);extent.grow(16,16);
                        if(!extent.intersects(damage))continue;
                        var rounded=new RoundRectangle2D.Double(b.x,b.y,b.width,b.height,24,24);
                        if(rounded.contains(damage))continue;
                        Area outside=new Area(damage);outside.subtract(new Area(rounded));
                        Graphics2D shadow=(Graphics2D)g.create();shadow.clip(outside);
                        for(Container parent=surface.getParent();parent!=null&&parent!=layer;parent=parent.getParent())
                            if(parent instanceof JViewport){
                                Point p=SwingUtilities.convertPoint(parent,0,0,layer);
                                shadow.clip(new Rectangle(p.x,p.y,parent.getWidth(),parent.getHeight()));
                            }
                        String kind=(String)surface.getClientProperty("mist.shadow");
                        if(shadow.getClipBounds()!=null&&!shadow.getClipBounds().isEmpty())paintShadow(shadow,b,kind);
                        shadow.dispose();
                    }
                }finally{g.dispose();}
            }
            private void collect(Container parent,List<JComponent> result,JComponent layer,Rectangle damage){
                for(Component child:parent.getComponents())if(child.isVisible()){
                    Rectangle extent=SwingUtilities.convertRectangle(parent,child.getBounds(),layer);
                    extent.grow(20,20);
                    if(!extent.intersects(damage))continue;
                    if(child instanceof JComponent widget&&widget.getClientProperty("mist.shadow")!=null)result.add(widget);
                    if(child instanceof Container nested&&!(child instanceof javax.swing.text.JTextComponent)
                        &&!(child instanceof AbstractButton)&&!(child instanceof JComboBox<?>)
                        &&!(child instanceof JScrollBar)&&!(child instanceof CellRendererPane))collect(nested,result,layer,damage);
                }
            }
        });
    }
    /** Cached tiles for a quiz card; callers reserve 16px outside the card. */
    public static void paintQuizCardShadow(Graphics2D graphics,Rectangle bounds){
        paintShadow(graphics,bounds,"quiz");
    }
    /** Home assistant uses one tiny shared nine-slice shadow, independent of window size. */
    public static void paintAssistantShadow(Graphics2D graphics,Rectangle bounds){
        Graphics2D shadow=(Graphics2D)graphics.create();
        try{
            shadow.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BILINEAR);
            paintShadow(shadow,bounds,"assistant");
        }finally{shadow.dispose();}
    }
    /** Mentor uses its own lighter, higher-density cached shadow. */
    public static void paintMentorShadow(Graphics2D graphics,Rectangle bounds){
        Graphics2D shadow=(Graphics2D)graphics.create();
        try{shadow.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BILINEAR);paintShadow(shadow,bounds,"mentor");}
        finally{shadow.dispose();}
    }
    /** Reuse eight small raster tiles; straight edges stretch without rerasterizing blur paths. */
    private static void paintShadow(Graphics2D g,Rectangle bounds,String kind){
        if(bounds.width<40||bounds.height<40)return;
        boolean mentor="mentor".equals(kind),assistant="assistant".equals(kind)||mentor;
        int outset=assistant?20:16;
        int density=mentor?4:2;
        BufferedImage patch;
        synchronized(SHADOW_PATCHES){patch=SHADOW_PATCHES.computeIfAbsent(kind,key->{
            BufferedImage image=new BufferedImage((40+outset*2)*density,(40+outset*2)*density,
                mentor?BufferedImage.TYPE_INT_ARGB_PRE:BufferedImage.TYPE_INT_ARGB);
            Graphics2D raster=image.createGraphics();
            try{
                raster.scale(density,density);raster.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                Rectangle template=new Rectangle(outset,outset,assistant?39:40,assistant?39:40);
                if("mentor".equals(key)){
                    filledShadow(raster,template,20,3,.20,12);
                    filledShadow(raster,template,4,0,.10,12);
                }else if("assistant".equals(key)) {
                    // Keep the card outline at 1:1 scale; only the blur extends outward.
                    // Filled layers avoid a transparent seam beside the card edge.
                    filledShadow(raster,template,18,3,.32,11);
                    filledShadow(raster,template,4,0,.24,11);
                }
                else if("quiz".equals(key))shadow(raster,template,12,3,.09,18);
                else if("answer".equals(key))shadow(raster,template,4,1,.0225,12);
                else if("input".equals(key))shadow(raster,template,12,3,.054,12);
                else {shadow(raster,template,10,2,.0405,12);shadow(raster,template,2,1,.0225,12);}
            }finally{raster.dispose();}
            return image;
        });}
        int[] source={0,(outset+20)*density,(outset+21)*density,patch.getWidth()};
        int[] x={bounds.x-outset,bounds.x+20,bounds.x+bounds.width-19,bounds.x+bounds.width+outset};
        int[] y={bounds.y-outset,bounds.y+20,bounds.y+bounds.height-19,bounds.y+bounds.height+outset};
        for(int row=0;row<3;row++)for(int column=0;column<3;column++)if(row!=1||column!=1)
            g.drawImage(patch,x[column],y[row],x[column+1],y[row+1],
                source[column],source[row],source[column+1],source[row+1],null);
    }
    private static void filledShadow(Graphics2D g,Rectangle b,int blur,int offset,double opacity,int radius){
        double sigma=Math.max(.7,blur/3d);
        for(int distance=blur;distance>=0;distance--){
            double outer=Math.exp(-(distance+1d)*(distance+1d)/(2*sigma*sigma));
            double inner=Math.exp(-distance*(double)distance/(2*sigma*sigma));
            int alpha=(int)Math.round(255*opacity*(inner-outer));
            if(alpha==0)continue;
            g.setColor(new Color(SHADOW.getRed(),SHADOW.getGreen(),SHADOW.getBlue(),alpha));
            g.fill(new RoundRectangle2D.Double(b.x-distance+.5,b.y+offset-distance+.5,
                b.width+2*distance,b.height+2*distance,2*(radius+distance),2*(radius+distance)));
        }
    }
    private static void shadow(Graphics2D g,Rectangle b,int blur,int offset,double opacity,int radius){
        double sigma=Math.max(.7,blur/3d);
        for(int distance=blur;distance>=0;distance--){
            int alpha=(int)Math.round(255*opacity*.5*Math.exp(-distance*distance/(2*sigma*sigma)));
            if(alpha==0)continue;
            g.setColor(new Color(SHADOW.getRed(),SHADOW.getGreen(),SHADOW.getBlue(),alpha));
            g.draw(new RoundRectangle2D.Double(b.x-distance-.5,b.y+offset-distance-.5,
                b.width+2*distance,b.height+2*distance,2*(radius+distance),2*(radius+distance)));
        }
    }
    public static class Panel extends JPanel {
        private final int radius;
        private final Color fill,outline;
        private RoundedPanelEdges smoothEdges;
        public Panel(LayoutManager layout,int radius,Color fill,Color outline){
            super(layout);this.radius=radius;this.fill=fill;this.outline=outline;setOpaque(false);
            putClientProperty("mist.shadow","pane");
            setBorder(new EmptyBorder(1,1,1,1));
        }
        @Override protected void paintComponent(Graphics graphics){
            Graphics2D g=(Graphics2D)graphics.create();
            try{
                var shape=new RoundRectangle2D.Double(.5,.5,getWidth()-1,getHeight()-1,radius*2,radius*2);
                Rectangle damage=g.getClipBounds();g.setColor(fill);
                if(Boolean.TRUE.equals(getClientProperty("mist.smoothCorners")))g.fillRect(0,0,getWidth(),getHeight());
                else if(damage!=null&&shape.contains(damage))g.fillRect(damage.x,damage.y,damage.width,damage.height);
                else {g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);g.fill(shape);}
            }
            finally{g.dispose();}super.paintComponent(graphics);
        }
        @Override public void paint(Graphics graphics){
            Graphics2D g=(Graphics2D)graphics.create();
            try{
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                Rectangle damage=g.getClipBounds();
                if(radius>0&&getWidth()>2*(radius+2)&&getHeight()>2*(radius+2)
                        &&Boolean.TRUE.equals(getClientProperty("mist.smoothCorners"))){
                    if(smoothEdges==null)smoothEdges=new RoundedPanelEdges();
                    smoothEdges.paint(this,g,radius,this::paintSurface);
                    paintOutline(g,damage);return;
                }
                var shape=new RoundRectangle2D.Double(0,0,getWidth(),getHeight(),radius*2,radius*2);
                // Interior damage cannot reach a rounded corner. Keep its simple
                // rectangular GPU clip instead of building nested span masks.
                if(damage==null||!shape.contains(damage))g.clip(shape);
                super.paint(g);
                paintOutline(g,damage);
            }finally{g.dispose();}
        }
        private void paintSurface(Graphics2D graphics){super.paint(graphics);}
        private void paintOutline(Graphics2D g,Rectangle damage){
            var interior=new RoundRectangle2D.Double(2,2,getWidth()-4,getHeight()-4,Math.max(0,radius*2-4),Math.max(0,radius*2-4));
            if(outline!=null&&(damage==null||!interior.contains(damage))){g.setColor(outline);g.draw(new RoundRectangle2D.Double(.5,.5,getWidth()-1,getHeight()-1,radius*2,radius*2));}
        }
    }
    public static void textSizeDialog(Component owner,JSlider target,String title,boolean instructions){
        textSizeDialog(owner,target,title,instructions,"pt");
    }
    public static void textSizeDialog(Component owner,JSlider target,String title,boolean instructions,String unit){
        JSlider slider=new JSlider(target.getMinimum(),target.getMaximum(),target.getValue());
        JSpinner number=new JSpinner(new SpinnerNumberModel(target.getValue(),target.getMinimum(),target.getMaximum(),1));
        boolean[] updating={false};
        slider.addChangeListener(e->{if(updating[0])return;updating[0]=true;number.setValue(slider.getValue());target.setValueIsAdjusting(slider.getValueIsAdjusting());target.setValue(slider.getValue());updating[0]=false;});
        number.addChangeListener(e->{if(updating[0])return;updating[0]=true;slider.setValue((int)number.getValue());target.setValueIsAdjusting(false);target.setValue((int)number.getValue());updating[0]=false;});
        JPanel panel=new JPanel(new BorderLayout(12,12));panel.setBorder(new EmptyBorder(16,16,16,16));panel.setBackground(PAPER);
        JPanel row=new JPanel(new BorderLayout(12,0));row.setOpaque(false);row.add(label("글자 크기 ("+unit+")",13,TEXT,Font.PLAIN),BorderLayout.WEST);row.add(number,BorderLayout.EAST);
        panel.add(row,BorderLayout.NORTH);panel.add(slider,BorderLayout.CENTER);
        if(instructions){JTextArea placeholder=new JTextArea("사용자 맞춤 지침\n다음 업데이트에서 사용할 수 있어요.",3,26);placeholder.setEditable(false);placeholder.setBackground(SOFT);placeholder.setFont(font(Font.PLAIN,12));placeholder.setForeground(MUTED);placeholder.setBorder(new EmptyBorder(12,12,12,12));panel.add(placeholder,BorderLayout.SOUTH);}
        JOptionPane.showMessageDialog(owner,panel,title,JOptionPane.PLAIN_MESSAGE);
        target.setValueIsAdjusting(false);
    }
}
