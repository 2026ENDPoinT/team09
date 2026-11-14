package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.StudyTheme;

import javax.swing.*;
import javax.swing.border.EmptyBorder;
import java.awt.*;
import java.awt.event.HierarchyEvent;
import java.awt.event.WindowAdapter;
import java.awt.event.WindowEvent;
import java.awt.geom.Path2D;
import java.awt.image.BufferedImage;
import java.util.EnumMap;
import java.util.function.Consumer;

/** Expanding native buttons with a cached, static lava treatment for the practice set. */
final class QuizModeSelector extends JPanel {
    private static final Color INK=new Color(0x191919), PAPER=Color.WHITE,
        LINE=new Color(0xcbc8bd), ACID=Color.WHITE, FIRE=new Color(0xf0442d),
        BASALT=new Color(0x241a17), WARM_PAPER=new Color(0xfffbf7);
    private static final int HEIGHT=62,GAP=6,SEPARATION=10;
    private static final long DURATION=420_000_000L;
    private final EnumMap<QuizPanel.Theme,JToggleButton> buttons;
    private final double[] weights=new double[4],fromWeights=new double[4],toWeights=new double[4],
        emphasis=new double[4],fromEmphasis=new double[4],toEmphasis=new double[4];
    private final Timer timer;
    private QuizPanel.Theme selected=QuizPanel.Theme.CONCEPT;
    private long started;
    private boolean moving,paused;
    private Window observedWindow;
    private final WindowAdapter windowActivity=new WindowAdapter(){
        @Override public void windowActivated(WindowEvent event){updateTimer();}
        @Override public void windowDeactivated(WindowEvent event){finishMotion();}
        @Override public void windowIconified(WindowEvent event){finishMotion();}
        @Override public void windowDeiconified(WindowEvent event){updateTimer();}
    };

    QuizModeSelector(EnumMap<QuizPanel.Theme,JToggleButton> buttons,Consumer<QuizPanel.Theme> onSelect) {
        this.buttons=buttons;setLayout(null);setBackground(Color.WHITE);setOpaque(true);
        setAlignmentX(Component.LEFT_ALIGNMENT);
        getAccessibleContext().setAccessibleName("문제집 유형 선택");
        ButtonGroup group=new ButtonGroup();
        for(QuizPanel.Theme theme:QuizPanel.Theme.values()) {
            ModeButton button=new ModeButton(theme);buttons.put(theme,button);group.add(button);add(button);
            button.addActionListener(event->{select(theme,true);onSelect.accept(theme);});
        }
        timer=new Timer(16,event->tick());timer.setCoalesce(true);
        addHierarchyListener(event->{
            if((event.getChangeFlags()&HierarchyEvent.SHOWING_CHANGED)!=0)updateTimer();
        });
        select(selected,false);
    }

    void select(QuizPanel.Theme theme,boolean animate) {
        if(theme==null)return;
        updateAnimation(System.nanoTime());
        selected=theme;
        for(QuizPanel.Theme candidate:QuizPanel.Theme.values()) {
            int index=candidate.ordinal();
            buttons.get(candidate).setSelected(candidate==theme);
            fromWeights[index]=weights[index];fromEmphasis[index]=emphasis[index];
            toWeights[index]=candidate==theme?1.45:.72;
            toEmphasis[index]=candidate==theme?1:0;
        }
        moving=animate&&isShowing()&&!getVisibleRect().isEmpty()&&!paused&&!reducedMotion();
        started=System.nanoTime();
        if(!moving)finish();
        doLayout();repaint();updateTimer();
    }

    void pause(){paused=true;finishMotion();}
    void resume(){paused=false;updateTimer();}
    private static boolean reducedMotion(){
        return Boolean.getBoolean("synesis.reduceMotion")||Boolean.TRUE.equals(UIManager.get("synesis.reduceMotion"));
    }

    @Override public void removeNotify(){
        finishMotion();
        if(observedWindow!=null){observedWindow.removeWindowListener(windowActivity);observedWindow=null;}
        super.removeNotify();
    }
    @Override public void addNotify(){
        super.addNotify();observedWindow=SwingUtilities.getWindowAncestor(this);
        if(observedWindow!=null)observedWindow.addWindowListener(windowActivity);
        updateTimer();
    }

    private boolean windowActive(){
        return observedWindow==null||observedWindow.isActive()
            &&(!(observedWindow instanceof Frame frame)||(frame.getExtendedState()&Frame.ICONIFIED)==0);
    }

    private void updateTimer() {
        if(timer==null)return;
        if(!isShowing()||getVisibleRect().isEmpty()||paused||reducedMotion()||!windowActive()){finishMotion();return;}
        if(!moving){timer.stop();return;}
        timer.setDelay(16);
        if(!timer.isRunning())timer.start();
    }

    private void tick() {
        if(!isShowing()||getVisibleRect().isEmpty()||paused||reducedMotion()||!windowActive()){finishMotion();return;}
        updateAnimation(System.nanoTime());
        doLayout();repaint();
        if(!moving)timer.stop();
    }

    private void updateAnimation(long now) {
        if(!moving)return;
        double elapsed=Math.min(1,(now-started)/(double)DURATION),progress=ease(elapsed);
        for(int index=0;index<4;index++) {
            weights[index]=fromWeights[index]+(toWeights[index]-fromWeights[index])*progress;
            emphasis[index]=fromEmphasis[index]+(toEmphasis[index]-fromEmphasis[index])*progress;
        }
        if(elapsed>=1)finish();
    }

    private void finish() {
        for(int index=0;index<4;index++) {
            weights[index]=toWeights[index];emphasis[index]=toEmphasis[index];
        }
        moving=false;
    }

    private void finishMotion() {
        timer.stop();
        if(moving){finish();doLayout();}
    }

    /** CSS cubic-bezier(.22,1,.36,1), inverted by x so timing stays true to the reference. */
    private static double ease(double x) {
        double low=0,high=1,t=x;
        for(int count=0;count<15;count++) {
            double u=1-t,at=3*u*u*t*.22+3*u*t*t*.36+t*t*t;
            if(at<x)low=t;else high=t;t=(low+high)/2;
        }
        return 1-Math.pow(1-t,3);
    }

    @Override public Dimension getPreferredSize(){return new Dimension(460,HEIGHT+15);}
    @Override public Dimension getMaximumSize(){return new Dimension(Integer.MAX_VALUE,HEIGHT+15);}
    @Override public Dimension getMinimumSize(){
        int width=GAP*3+SEPARATION;
        for(JToggleButton button:buttons.values())width+=minimumWidth(button);
        return new Dimension(width,HEIGHT+15);
    }

    private int minimumWidth(JToggleButton button) {
        return button.getFontMetrics(button.getFont()).stringWidth(button.getText())+16;
    }

    @Override public void doLayout() {
        if(buttons.isEmpty())return;
        int available=Math.max(0,getWidth()-GAP*3-SEPARATION);
        double[] widths=new double[4];boolean[] fixed=new boolean[4];
        double remaining=available,weight=0;
        for(double item:weights)weight+=item;
        // Preserve every Korean label before allocating the flexible width.
        for(int pass=0;pass<4;pass++) {
            boolean changed=false;
            for(QuizPanel.Theme theme:QuizPanel.Theme.values()) {
                int index=theme.ordinal();if(fixed[index])continue;
                double nominal=weight>0?remaining*weights[index]/weight:remaining/4;
                int minimum=minimumWidth(buttons.get(theme));
                if(nominal<minimum) {
                    widths[index]=minimum;fixed[index]=true;
                    remaining-=minimum;weight-=weights[index];changed=true;
                }
            }
            if(!changed)break;
        }
        for(int index=0;index<4;index++)if(!fixed[index])
            widths[index]=Math.max(0,weight>0?remaining*weights[index]/weight:remaining/4);
        int x=0;
        for(QuizPanel.Theme theme:QuizPanel.Theme.values()) {
            if(theme==QuizPanel.Theme.RECALL)x+=SEPARATION;
            int index=theme.ordinal(),width=(int)Math.round(widths[index]);
            if(index==3)width=Math.max(0,getWidth()-x);
            buttons.get(theme).setBounds(x,0,width,HEIGHT);x+=width+GAP;
        }
    }

    @Override protected void paintComponent(Graphics graphics) {
        super.paintComponent(graphics);
        Graphics2D g=(Graphics2D)graphics.create();
        try {
            g.setColor(INK);g.drawLine(0,HEIGHT+13,getWidth(),HEIGHT+13);
            JToggleButton recall=buttons.get(QuizPanel.Theme.RECALL);
            if(recall!=null){g.setColor(new Color(0xbab7ae));g.drawLine(recall.getX()-8,4,recall.getX()-8,HEIGHT-4);}
        } finally {g.dispose();}
        // Idle buttons have no clock or periodic repaint. Only selection moves.
        if(moving&&!timer.isRunning()&&isShowing()&&!getVisibleRect().isEmpty())updateTimer();
    }

    private final class ModeButton extends JToggleButton {
        private final QuizPanel.Theme theme;
        ModeButton(QuizPanel.Theme theme) {
            super(theme.title);this.theme=theme;
            putClientProperty("synesis.preserveButton",true);putClientProperty("synesis.preserveFont",true);
            setFont(StudyTheme.font(Font.BOLD,12));setBorder(new EmptyBorder(0,0,0,0));
            setOpaque(false);setContentAreaFilled(false);setBorderPainted(false);setFocusPainted(false);
            setRolloverEnabled(true);setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));
            setToolTipText(theme==QuizPanel.Theme.PRACTICE?theme.title+" · 고난도 실전 연습":theme.title);
            setPreferredSize(new Dimension(100,HEIGHT));
            getAccessibleContext().setAccessibleDescription(theme==QuizPanel.Theme.PRACTICE
                ?"고난도 실전 문제집. 선택하면 넓어져요.":"선택하면 문제집 표지가 바뀌고 버튼이 넓어져요.");
        }
        @Override protected void paintComponent(Graphics graphics) {
            Graphics2D g=(Graphics2D)graphics.create();
            try {
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING,RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
                double active=emphasis[theme.ordinal()];boolean fiery=theme==QuizPanel.Theme.PRACTICE;
                Color background=blend(fiery?WARM_PAPER:PAPER,fiery?BASALT:INK,active);
                if(!isEnabled())g.setComposite(AlphaComposite.SrcOver.derive(.58f));
                g.setColor(background);g.fillRoundRect(0,0,getWidth()-1,getHeight()-1,3,3);
                if(fiery)paintLava(g,getWidth(),getHeight(),active);
                g.setColor(blend(getModel().isRollover()?new Color(0x77766f):fiery?new Color(0xe3aa91):LINE,fiery?new Color(0xa34b30):INK,active));
                g.drawRoundRect(0,0,getWidth()-1,getHeight()-1,3,3);
                if(active>.001) {
                    g.setColor(fiery?FIRE:ACID);g.fillRect(1,getHeight()-4,(int)((getWidth()-2)*active),3);
                }
                g.setFont(StudyTheme.font(Font.BOLD,8));g.setColor(blend(new Color(0x8d8b84),new Color(0xb7b7a8),active));
                g.drawString("0"+(theme.ordinal()+1),8,13);
                g.setFont(getFont());FontMetrics metrics=g.getFontMetrics();
                int textWidth=metrics.stringWidth(getText()),x=(getWidth()-textWidth)/2,y=(getHeight()+metrics.getAscent()-metrics.getDescent())/2+2;
                g.setColor(fiery?blend(new Color(0xe74329),new Color(0xffd5a1),active):blend(INK,PAPER,active));
                g.drawString(getText(),x,y);
                if(active>.7&&getWidth()>textWidth+34) {
                    g.setColor(fiery?new Color(0xff8c3c):ACID);g.fillOval(x+textWidth+7,y-6,4,4);
                }
                if(isFocusOwner()) {
                    g.setStroke(new BasicStroke(1.5f));g.setColor(fiery?new Color(0xffa343):Color.WHITE);
                    g.drawRoundRect(3,3,getWidth()-7,getHeight()-7,3,3);
                }
            } finally {g.dispose();}
        }
    }

    private static Color blend(Color from,Color to,double progress) {
        double p=Math.max(0,Math.min(1,progress));
        return new Color((int)(from.getRed()+(to.getRed()-from.getRed())*p),
            (int)(from.getGreen()+(to.getGreen()-from.getGreen())*p),
            (int)(from.getBlue()+(to.getBlue()-from.getBlue())*p));
    }

    private static void paintLava(Graphics2D graphics,int width,int height,double active) {
        Graphics2D g=(Graphics2D)graphics.create();
        try {
            g.clipRect(1,1,Math.max(0,width-2),Math.max(0,height-3));
            g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BILINEAR);
            float base=((AlphaComposite)g.getComposite()).getAlpha();
            int top=height*LavaArt.TOP/LavaArt.HEIGHT;
            if(active<.999) {
                g.setComposite(AlphaComposite.SrcOver.derive(base*(float)(1-active)));
                g.drawImage(LavaArt.LIGHT,0,top,width,height-top,null);
            }
            if(active>.001) {
                g.setComposite(AlphaComposite.SrcOver.derive(base*(float)active));
                g.drawImage(LavaArt.DARK,0,top,width,height-top,null);
            }
        } finally {g.dispose();}
    }

    /** Two small 2x layers are built once; resizing only stretches the cached art. */
    private static final class LavaArt {
        private static final int WIDTH=320,HEIGHT=62,TOP=29,SCALE=2;
        static final BufferedImage LIGHT=create(false),DARK=create(true);
        private static BufferedImage create(boolean dark) {
            BufferedImage image=new BufferedImage(WIDTH*SCALE,(HEIGHT-TOP)*SCALE,BufferedImage.TYPE_INT_ARGB_PRE);
            Graphics2D g=image.createGraphics();
            try {
                g.scale(SCALE,SCALE);
                g.translate(0,-TOP);
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                g.setPaint(new GradientPaint(0,HEIGHT,new Color(255,87,30,dark?96:25),0,29,new Color(255,133,53,0)));
                g.fillRect(0,29,WIDTH,HEIGHT-29);
                Path2D pool=new Path2D.Float();
                pool.moveTo(0,53);pool.curveTo(26,44,42,53,65,50);
                pool.curveTo(88,47,105,42,129,48);pool.curveTo(152,54,165,41,185,46);
                pool.curveTo(205,50,231,43,248,48);pool.curveTo(274,53,296,43,320,48);
                pool.lineTo(320,62);pool.lineTo(0,62);pool.closePath();
                g.setPaint(new GradientPaint(0,43,new Color(255,177,76,dark?245:112),0,62,new Color(232,57,26,dark?240:140)));
                g.fill(pool);
                Path2D rock=new Path2D.Float();
                rock.moveTo(12,62);rock.lineTo(31,54);rock.lineTo(55,53);rock.lineTo(70,57);
                rock.lineTo(97,53);rock.lineTo(120,55);rock.lineTo(143,62);rock.closePath();
                rock.moveTo(166,62);rock.lineTo(193,53);rock.lineTo(215,56);rock.lineTo(241,52);
                rock.lineTo(274,55);rock.lineTo(297,62);rock.closePath();
                g.setColor(dark?new Color(0x33231d):new Color(0xb6765c));g.fill(rock);
                Path2D cracks=new Path2D.Float();
                cracks.moveTo(48,62);cracks.lineTo(53,55);cracks.lineTo(46,50);cracks.lineTo(52,45);cracks.lineTo(50,40);
                cracks.moveTo(46,50);cracks.lineTo(36,48);cracks.lineTo(32,43);
                cracks.moveTo(130,62);cracks.lineTo(135,57);cracks.lineTo(126,52);cracks.lineTo(132,47);
                cracks.moveTo(240,62);cracks.lineTo(229,57);cracks.lineTo(235,52);cracks.lineTo(230,46);cracks.lineTo(236,41);
                cracks.moveTo(235,52);cracks.lineTo(249,49);cracks.lineTo(255,44);
                g.setStroke(new BasicStroke(3f,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));
                g.setColor(new Color(255,80,27,dark?156:46));g.draw(cracks);
                g.setStroke(new BasicStroke(.9f,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));
                g.setColor(new Color(255,207,107,dark?250:145));g.draw(cracks);
            } finally {g.dispose();}
            return image;
        }
    }
}
