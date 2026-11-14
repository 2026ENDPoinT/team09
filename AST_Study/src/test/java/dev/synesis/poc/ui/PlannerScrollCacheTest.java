package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;
import java.awt.image.BufferedImage;

/** Pixel equivalence, dirty content during scroll, transparency, scale and bounded painting. */
public final class PlannerScrollCacheTest {
    static int checks;
    static final class Content extends JPanel {
        long paintedArea;JButton button=new JButton("변경 전");
        Content(boolean transparent){super(null);setOpaque(!transparent);setBackground(Color.WHITE);setSize(260,1000);button.setUI(new javax.swing.plaf.basic.BasicButtonUI());button.setBounds(40,100,130,32);add(button);}
        @Override protected void paintComponent(Graphics graphics){
            super.paintComponent(graphics);Rectangle clip=graphics.getClipBounds();paintedArea+=(long)clip.width*clip.height;
            Graphics2D g=(Graphics2D)graphics.create();g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
            for(int y=0;y<1000;y+=29){g.setColor(new Color((y*3)%220,80,160,isOpaque()?255:75));g.fillRoundRect(10,y,220,18,9,9);g.setColor(Color.BLACK);g.drawString("일정 "+y,22,y+14);}g.dispose();
        }
    }
    static final class Fixture {
        ScrollCacheViewport view=new ScrollCacheViewport();Content body;
        Fixture(boolean cache,boolean transparent){body=new Content(transparent);view.setOpaque(!transparent);view.setBackground(Color.WHITE);view.setSize(260,230);view.setView(body);view.setViewSize(new Dimension(260,1000));view.setCacheEnabled(cache);}
    }
    public static void main(String[] args)throws Exception{
        SwingUtilities.invokeAndWait(()->{
            for(boolean transparent:new boolean[]{false,true})for(double scale:new double[]{1,2,1.25}){
                Fixture cached=new Fixture(true,transparent),plain=new Fixture(false,transparent);
                for(int y:new int[]{0,7,18,80,200,193,0,600,770}){
                    cached.view.setViewPosition(new Point(0,y));plain.view.setViewPosition(new Point(0,y));
                    equal(paint(cached.view,scale,null),paint(plain.view,scale,null),"scroll "+y+" scale "+scale+" alpha "+transparent);
                }
                cached.view.setViewPosition(new Point(0,70));plain.view.setViewPosition(new Point(0,70));
                cached.body.button.setText("スクロール 중 수정");plain.body.button.setText("スクロール 중 수정");
                equal(paint(cached.view,scale,null),paint(plain.view,scale,null),"edit after wheel before paint");
                cached.body.button.getModel().setPressed(true);plain.body.button.getModel().setPressed(true);
                cached.view.setViewPosition(new Point(0,72));plain.view.setViewPosition(new Point(0,72));
                equal(paint(cached.view,scale,null),paint(plain.view,scale,null),"pressed state then scroll");
                cached.view.setSize(220,190);plain.view.setSize(220,190);
                equal(paint(cached.view,scale,null),paint(plain.view,scale,null),"resized");
                equal(paint(cached.view,scale==2?1:2,null),paint(plain.view,scale==2?1:2,null),"device scale changed");
            }
            Fixture f=new Fixture(true,false);paint(f.view,2,null);f.body.paintedArea=0;
            f.view.setViewPosition(new Point(0,9));paint(f.view,2,null);
            check(f.body.paintedArea==260*9,"scroll must paint only exposed 9px strip: "+f.body.paintedArea);
            f.body.paintedArea=0;paint(f.view,2,new Rectangle(50,60,24,20));
            check(f.body.paintedArea==24*20,"local animation/hover damage expanded: "+f.body.paintedArea);
            fadingThumb();
            System.out.println("PlannerScrollCacheTest passed: "+checks+" checks; 9px scroll paints 3.91% of viewport; 24x20 damage stays local");
        });System.exit(0);
    }
    static void fadingThumb(){
        try{
            FadeScrollPane pane=new FadeScrollPane(new Content(false),JScrollPane.VERTICAL_SCROLLBAR_ALWAYS,JScrollPane.HORIZONTAL_SCROLLBAR_NEVER);
            pane.getViewport().getView().setPreferredSize(new Dimension(260,1000));pane.setScrollCacheEnabled(true);pane.setSize(280,230);
            FadingScrollBarUI ui=new FadingScrollBarUI(Color.BLACK,.25f);JScrollBar bar=pane.getVerticalScrollBar();bar.setUI(ui);
            PlannerIncrementalRenderTest.layout(pane);pane.getViewport().doLayout();bar.doLayout();
            var opacity=FadingScrollBarUI.class.getDeclaredField("opacity");opacity.setAccessible(true);opacity.setFloat(ui,1f);
            BufferedImage previous=paint(pane,2,null);
            RepaintManager old=RepaintManager.currentManager(pane);Rectangle[] damage={null};
            RepaintManager meter=new RepaintManager(){@Override public void addDirtyRegion(JComponent c,int x,int y,int w,int h){if(c==bar)damage[0]=new Rectangle(x,y,w,h);}};
            RepaintManager.setCurrentManager(meter);
            try{
                opacity.setFloat(ui,.5f);var request=FadingScrollBarUI.class.getDeclaredMethod("repaintThumb");request.setAccessible(true);request.invoke(ui);
                check(damage[0]!=null&&damage[0].height<bar.getHeight(),"fade animation repainted entire scrollbar");
                Rectangle rect=SwingUtilities.convertRectangle(bar,damage[0],pane);Graphics2D g=previous.createGraphics();g.scale(2,2);g.setClip(rect);pane.paint(g);g.dispose();
                equal(previous,paint(pane,2,null),"partial translucent scrollbar animation");
            }finally{RepaintManager.setCurrentManager(old);bar.setUI(new javax.swing.plaf.basic.BasicScrollBarUI());}
        }catch(Exception e){throw new RuntimeException(e);}
    }
    static BufferedImage paint(JComponent c,double scale,Rectangle clip){
        BufferedImage image=new BufferedImage((int)Math.ceil(c.getWidth()*scale),(int)Math.ceil(c.getHeight()*scale),BufferedImage.TYPE_INT_RGB);
        Graphics2D g=image.createGraphics();g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING,RenderingHints.VALUE_TEXT_ANTIALIAS_ON);g.setColor(new Color(245,232,213));g.fillRect(0,0,image.getWidth(),image.getHeight());g.scale(scale,scale);g.setClip(clip==null?new Rectangle(0,0,c.getWidth(),c.getHeight()):clip);c.paint(g);g.dispose();return image;
    }
    static void equal(BufferedImage a,BufferedImage b,String context){
        int differences=0,max=0;for(int y=0;y<a.getHeight();y++)for(int x=0;x<a.getWidth();x++){
            int p=a.getRGB(x,y),q=b.getRGB(x,y);if(p!=q){differences++;for(int shift=0;shift<24;shift+=8)max=Math.max(max,Math.abs((p>>shift&255)-(q>>shift&255)));}
        }
        if(max>1)try{javax.imageio.ImageIO.write(a,"png",new java.io.File("build/planner-reuse-20261102/cache-actual.png"));javax.imageio.ImageIO.write(b,"png",new java.io.File("build/planner-reuse-20261102/cache-expected.png"));}catch(Exception e){throw new RuntimeException(e);}
        check(max<=1,context+": "+differences+" pixels differ, max "+max);
    }
    static void check(boolean ok,String message){checks++;if(!ok)throw new AssertionError(message);}
}
