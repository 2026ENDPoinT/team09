package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.MistWorkspaceTheme;

import dev.synesis.poc.ui.StudyTheme;
import javax.swing.*;
import java.awt.*;
import java.awt.event.HierarchyEvent;
import java.awt.event.ComponentAdapter;
import java.awt.event.ComponentEvent;
import java.awt.event.WindowAdapter;
import java.awt.event.WindowEvent;
import javax.swing.event.ChangeListener;
import java.awt.geom.*;
import java.awt.image.BufferedImage;

/** A code-drawn workbook cover adapted from the Make preview, with local-only motion. */
final class QuizBookPreview extends JPanel {
    private static final double DURATION_NANOS=520_000_000d;
    private static final Color INK=new Color(0x191919);
    private final Timer clock=new Timer(33,event->tick());
    private QuizPanel.Theme theme=QuizPanel.Theme.CONCEPT;
    private String difficulty="중";
    private int count=10;
    private long started;
    private double progress=1;
    private BufferedImage departing,staticLayer;
    private double cachedScale,lastDeviceScale=1;
    private Shape flameClip=new Rectangle(12,0,258,346);
    private Window observedWindow;
    private JViewport observedViewport;
    private final ChangeListener viewportChange=event->refreshClock();
    private final WindowAdapter windowChange=new WindowAdapter(){
        @Override public void windowActivated(WindowEvent event){refreshClock();repaint();}
        @Override public void windowDeactivated(WindowEvent event){finishMotion();repaint();}
        @Override public void windowIconified(WindowEvent event){finishMotion();}
        @Override public void windowDeiconified(WindowEvent event){refreshClock();repaint();}
    };

    QuizBookPreview() {
        setOpaque(true);setBackground(Color.WHITE);setFocusable(false);
        setPreferredSize(new Dimension(280,360));setMinimumSize(new Dimension(160,220));
        putClientProperty("synesis.preserveFont",Boolean.TRUE);
        clock.setCoalesce(true);
        addHierarchyListener(event->{
            if((event.getChangeFlags()&HierarchyEvent.SHOWING_CHANGED)!=0) {
                if(isShowing()){watchAncestors();refreshClock();}else finishMotion();
            }
        });
        addComponentListener(new ComponentAdapter(){
            @Override public void componentResized(ComponentEvent event){refreshClock();}
        });
        updateAccessibleDescription();
    }

    void setSelection(QuizPanel.Theme selected,String level,int total,boolean animate) {
        if(selected==null)return;
        String nextLevel=level==null||level.isBlank()?"중":level;
        int nextCount=Math.max(1,total);
        if(theme==selected&&difficulty.equals(nextLevel)&&count==nextCount)return;
        boolean change=theme!=selected;
        boolean moving=change&&animate&&isShowing()&&!getVisibleRect().isEmpty()&&!reducedMotion();
        BufferedImage before=moving?snapshot():null;
        theme=selected;difficulty=nextLevel;count=nextCount;staticLayer=null;
        if(moving) {
            departing=before;progress=0;started=System.nanoTime();
        } else {departing=null;progress=1;}
        updateAccessibleDescription();refreshClock();repaint();
    }

    private void updateAccessibleDescription() {
        getAccessibleContext().setAccessibleName(theme.title+" 문제집 표지 미리보기");
        getAccessibleContext().setAccessibleDescription(theme.title+" 문제집 · "+theme.profileTargetDescription()+" · "+count+"문제");
    }

    private static boolean reducedMotion() {
        return Boolean.getBoolean("synesis.reduceMotion")||Boolean.TRUE.equals(UIManager.get("synesis.reduceMotion"));
    }

    private boolean canAnimate() {
        return isShowing()&&!getVisibleRect().isEmpty()&&!reducedMotion()
            &&(observedWindow==null||observedWindow.isActive());
    }

    private void refreshClock() {
        if(!canAnimate()){finishMotion();return;}
        if(progress<1||theme==QuizPanel.Theme.PRACTICE) {
            clock.setDelay(progress<1?16:42);
            if(!clock.isRunning())clock.start();
        } else clock.stop();
    }

    private void tick() {
        if(!canAnimate()){finishMotion();return;}
        if(progress<1) {
            progress=ease(Math.min(1,(System.nanoTime()-started)/DURATION_NANOS));
            if(progress>=1)departing=null;
            repaint();
        } else {
            // The opaque preview erases and redraws just the animated corner,
            // without propagating dirty pixels into the whole quiz page.
            double scale=bookScale();
            int x=(int)((getWidth()-326*scale)/2+145*scale);
            int y=(int)((getHeight()-434*scale)/2+155*scale);
            repaint(x,y,(int)Math.ceil(181*scale),(int)Math.ceil(225*scale));
        }
        refreshClock();
    }

    private void finishMotion() {clock.stop();progress=1;departing=null;}
    private void watchAncestors() {
        Window window=SwingUtilities.getWindowAncestor(this);
        JViewport viewport=(JViewport)SwingUtilities.getAncestorOfClass(JViewport.class,this);
        if(window!=observedWindow) {
            if(observedWindow!=null)observedWindow.removeWindowListener(windowChange);
            observedWindow=window;
            if(window!=null)window.addWindowListener(windowChange);
        }
        if(viewport!=observedViewport) {
            if(observedViewport!=null)observedViewport.removeChangeListener(viewportChange);
            observedViewport=viewport;
            if(viewport!=null)viewport.addChangeListener(viewportChange);
        }
    }
    @Override public void removeNotify(){
        finishMotion();staticLayer=null;cachedScale=0;
        if(observedWindow!=null)observedWindow.removeWindowListener(windowChange);
        if(observedViewport!=null)observedViewport.removeChangeListener(viewportChange);
        observedWindow=null;observedViewport=null;super.removeNotify();
    }
    @Override public void addNotify(){super.addNotify();watchAncestors();refreshClock();}

    private BufferedImage snapshot() {
        if(getWidth()<1||getHeight()<1)return null;
        double ratio=Math.min(lastDeviceScale,Math.min(1024d/getWidth(),1024d/getHeight()));
        BufferedImage image=new BufferedImage(Math.max(1,(int)Math.ceil(getWidth()*ratio)),
            Math.max(1,(int)Math.ceil(getHeight()*ratio)),BufferedImage.TYPE_INT_ARGB_PRE);
        Graphics2D graphics=image.createGraphics();
        try {graphics.scale(ratio,ratio);paintFrame(graphics);}finally {graphics.dispose();}
        return image;
    }

    @Override protected void paintComponent(Graphics graphics) {
        super.paintComponent(graphics);
        Graphics2D g=(Graphics2D)graphics.create();
        try {paintGrid(g);paintFrame(g);}finally {g.dispose();}
    }

    private void paintGrid(Graphics2D g) {
        int width=Math.min(310,Math.max(0,getWidth()-12)),height=Math.max(0,getHeight()-24);
        int left=(getWidth()-width)/2,top=12;
        g.setColor(MistWorkspaceTheme.SOFT);
        for(int x=left;x<=left+width;x+=26)g.drawLine(x,top,x,top+height);
        for(int y=top;y<=top+height;y+=26)g.drawLine(left,y,left+width,y);
    }

    private double bookScale(){return Math.max(.1,Math.min((getWidth()-20d)/326,(getHeight()-12d)/434));}

    private void ensureStaticLayer(Graphics2D target) {
        double device=Math.max(Math.abs(target.getTransform().getScaleX()),Math.abs(target.getTransform().getScaleY()));
        lastDeviceScale=Math.max(1,Math.min(2,device));
        double ratio=Math.min(2,Math.max(1,Math.ceil(bookScale()*lastDeviceScale*4)/4));
        if(staticLayer!=null&&cachedScale>=ratio)return;
        cachedScale=ratio;
        staticLayer=new BufferedImage((int)Math.ceil(326*ratio),(int)Math.ceil(434*ratio),BufferedImage.TYPE_INT_ARGB_PRE);
        Graphics2D g=staticLayer.createGraphics();
        try {
            g.scale(ratio,ratio);
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
            g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING,RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
            paintStaticBook(g);
        } finally {g.dispose();}
    }

    private void paintFrame(Graphics2D g) {
        ensureStaticLayer(g);
        g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
        g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BILINEAR);
        if(departing!=null&&progress<1) {
            g.setComposite(AlphaComposite.SrcOver.derive((float)(1-progress)));
            g.drawImage(departing,0,0,getWidth(),getHeight(),null);
        }
        g.setComposite(AlphaComposite.SrcOver.derive((float)progress));
        double scale=bookScale();
        g.translate((getWidth()-326*scale)/2,(getHeight()-434*scale)/2+(1-progress)*24*scale);
        g.scale(scale,scale);
        g.rotate(Math.toRadians(2*(1-progress)),158,209);
        g.drawImage(staticLayer,0,0,326,434,null);
        if(theme==QuizPanel.Theme.PRACTICE) {
            g.translate(23,16);g.rotate(Math.toRadians(-2),135,193);
            g.clip(flameClip);
            paintFlames(g,System.nanoTime()/1_000_000_000d);
        }
    }

    private void paintStaticBook(Graphics2D canvas) {
        Palette palette=palette(theme);
        for(int i=3;i>0;i--) {
            canvas.setColor(new Color(22,21,18,11));
            canvas.fill(new Ellipse2D.Double(24-i*5,387-i*2,276+i*10,17+i*5));
        }
        Graphics2D g=(Graphics2D)canvas.create();
        try {
            g.translate(23,16);g.rotate(Math.toRadians(-2),135,193);
            for(int i=3;i>=1;i--) {
                g.setColor(new Color(22,21,18,10));
                g.fillRoundRect(4+i*4,7+i*4,270,386,5,5);
            }
            g.setColor(new Color(0xe8e4d9));g.fillRoundRect(8,5,273,390,5,5);
            for(int i=0;i<5;i++) {
                g.setColor(new Color(95,88,73,i%2==0?48:18));
                g.drawLine(14,388+i,277,388+i);g.drawLine(274+i,12,274+i,386);
            }
            g.setColor(palette.cover);g.fillRoundRect(0,0,270,386,4,4);
            g.setColor(new Color(palette.deep.getRed(),palette.deep.getGreen(),palette.deep.getBlue(),25));
            for(int x=12;x<270;x+=21)g.drawLine(x,0,x,386);
            for(int y=0;y<386;y+=21)g.drawLine(12,y,269,y);
            g.setPaint(new GradientPaint(12,0,new Color(0,0,0,35),29,0,new Color(0,0,0,0)));
            g.fillRect(12,0,20,386);
            g.setColor(new Color(255,255,255,44));g.drawLine(14,1,14,384);
            g.setColor(palette.deep);g.fillRect(0,0,12,386);
            g.setColor(new Color(255,255,255,210));g.setFont(StudyTheme.font(Font.BOLD,6));
            Graphics2D spine=(Graphics2D)g.create();
            try {spine.rotate(Math.PI/2);spine.drawString(theme.title,18,-4);}finally {spine.dispose();}
            Color text=theme==QuizPanel.Theme.PRACTICE?new Color(0xf8eee8):INK;
            text(g,"MAKE YOUR TEST",27,25,7,Font.BOLD,text);
            right(g,"VOL. 01",250,25,7,text);
            text(g,palette.eyebrow,27,120,8,Font.BOLD,palette.accent);
            if(theme==QuizPanel.Theme.PRACTICE) {
                glow(g,105,159,83,new Color(255,75,40,44));
                coverTitle(g,theme.title,188,StudyTheme.font(Font.BOLD,64),palette.accent);
            } else {
                coverTitle(g,theme.title,163,serif(37),text);
            }
            text(g,palette.subtitle,27,198,11,Font.BOLD,theme==QuizPanel.Theme.PRACTICE?new Color(0xf5d5ca):palette.deep);
            g.setColor(palette.accent);g.fillRect(27,220,26,3);
            Color body=theme==QuizPanel.Theme.PRACTICE?new Color(0xb9a69e):palette.deep;
            text(g,palette.firstLine,27,244,8,Font.PLAIN,body);
            text(g,palette.secondLine,27,258,8,Font.PLAIN,body);
            String badge=theme.profileTargetDescription()+"  ·  "+count+"문제";
            g.setFont(StudyTheme.font(Font.BOLD,8));int badgeWidth=g.getFontMetrics().stringWidth(badge)+16;
            Area flameArea=new Area(new Rectangle(12,0,258,346));
            flameArea.subtract(new Area(new Rectangle(251-badgeWidth,306,badgeWidth+2,28)));flameClip=flameArea;
            g.setColor(text);g.drawRect(252-badgeWidth,307,badgeWidth,25);
            g.drawString(badge,260-badgeWidth,323);
            g.setColor(text);g.drawLine(27,346,252,346);
            text(g,"STUDY ARCHIVE",27,368,7,Font.BOLD,text);
            text(g,theme==QuizPanel.Theme.PRACTICE?"N°":"01",235,369,12,Font.BOLD,palette.accent);
            for(int i=0;i<3;i++) {
                g.setColor(new Color(palette.accent.getRed(),palette.accent.getGreen(),palette.accent.getBlue(),255-i*44));
                g.fillRoundRect(269,84+i*35,20,31,3,3);
                text(g,String.valueOf(i+1),277,103+i*35,7,Font.BOLD,Color.WHITE);
            }
        } finally {g.dispose();}
    }

    private static void paintFlames(Graphics2D g,double seconds) {
        double phase=reducedMotion()?0:seconds;
        flame(g,202,292,45,106+6*Math.sin(phase*4),17,.8f);
        flame(g,229,294,37,84+4*Math.sin(phase*3.4+1),38,.75f);
        flame(g,186,303,34,70+5*Math.sin(phase*3+2),-8,.75f);
    }

    private static void flame(Graphics2D graphics,double x,double y,double width,double height,double angle,float alpha) {
        Graphics2D g=(Graphics2D)graphics.create();
        try {
            g.translate(x,y);g.rotate(Math.toRadians(angle));
            Path2D shape=new Path2D.Double();shape.moveTo(0,0);
            shape.curveTo(-width*.7,-height*.25,-width*.2,-height*.65,width*.19,-height);
            shape.curveTo(width*.03,-height*.46,width*.71,-height*.57,width*.62,-height*.2);
            shape.curveTo(width*.56,height*.03,width*.15,height*.1,0,0);shape.closePath();
            float inherited=g.getComposite() instanceof AlphaComposite composite?composite.getAlpha():1;
            g.setComposite(AlphaComposite.SrcOver.derive(alpha*inherited));
            g.setPaint(new GradientPaint(0,(float)-height,new Color(0xff3d17),0,0,new Color(0xff9e2e)));
            g.fill(shape);g.scale(.42,.58);g.translate(12,0);
            g.setPaint(new GradientPaint(0,(float)-height,new Color(255,190,73,20),0,0,new Color(0xffd869)));
            g.fill(shape);
        } finally {g.dispose();}
    }

    private static void glow(Graphics2D g,float x,float y,float radius,Color color) {
        g.setPaint(new RadialGradientPaint(x,y,radius,new float[]{0,1},new Color[]{color,new Color(color.getRed(),color.getGreen(),color.getBlue(),0)}));
        g.fill(new Ellipse2D.Float(x-radius,y-radius,radius*2,radius*2));
    }
    private static void text(Graphics2D g,String value,int x,int y,int size,int style,Color color) {
        g.setFont(StudyTheme.font(style,size));g.setColor(color);g.drawString(value,x,y);
    }
    private static void right(Graphics2D g,String value,int x,int y,int size,Color color) {
        g.setFont(StudyTheme.font(Font.BOLD,size));g.setColor(color);g.drawString(value,x-g.getFontMetrics().stringWidth(value),y);
    }
    private static Font serif(int size) {
        Font font=new Font(Font.SERIF,Font.BOLD,size);
        return font.canDisplayUpTo("개념 완성")<0?font:StudyTheme.font(Font.BOLD,size);
    }
    private static void coverTitle(Graphics2D g,String title,int baseline,Font font,Color color) {
        int width=g.getFontMetrics(font).stringWidth(title);
        if(width>225)font=font.deriveFont(font.getSize2D()*225f/width);
        char[] characters = title.toCharArray();
        var glyphs = font.layoutGlyphVector(g.getFontRenderContext(), characters, 0,
                characters.length, Font.LAYOUT_LEFT_TO_RIGHT);
        // Java2D can omit Latin glyphs when drawing a rotated, mixed-script title at 2x.
        g.setColor(color);
        g.fill(glyphs.getOutline(25, baseline));
    }
    /** Invert cubic-bezier(.22,1,.36,1), matching the original book-in curve. */
    private static double ease(double time) {
        if(time>=1)return 1;
        double low=0,high=1,t=time;
        for(int i=0;i<14;i++) {
            double x=3*(1-t)*(1-t)*t*.22+3*(1-t)*t*t*.36+t*t*t;
            if(x<time)low=t;else high=t;t=(low+high)/2;
        }
        return 1-Math.pow(1-t,3);
    }
    private record Palette(Color cover,Color deep,Color accent,String eyebrow,String subtitle,String firstLine,String secondLine) {}
    private static Palette palette(QuizPanel.Theme theme) {
        return switch(theme) {
            case CONCEPT->new Palette(new Color(0xc6a477),new Color(0x5c3d26),new Color(0x9b432b),"FOUNDATION","핵심부터 차근차근","핵심 개념을 빈틈없이 다지는","정의와 조건 중심의 문제집");
            case UNDERSTANDING->new Palette(new Color(0xd9e0f2),new Color(0x243b76),new Color(0xf3c84b),"DEEP THINKING","한 단계 깊은 사고력","개념의 이유와 관계를 이해하는","사례 적용 중심의 문제집");
            case PRACTICE->new Palette(new Color(0x231511),new Color(0x0d0908),new Color(0xff4b28),"EXTREME ARCHIVE","조건을 넘나드는 실전 응용","낯선 상황과 복합 조건에 도전하는","고난도 실전 훈련 문제집");
            case RECALL->new Palette(new Color(0xf1dfb8),new Color(0x643c2f),new Color(0x3c6eab),"MEMORY CHECK","아는 것을 확실하게","핵심 용어와 필수 내용을 떠올리는","기억 점검 문제집");
        };
    }
}
