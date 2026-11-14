package dev.synesis.poc.pdf;

import javax.swing.*;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;

/** Exercise the actual effect layer's paint path, including a child-sized dirty repaint. */
public final class QuizCompletionMotionTest {
    public static void main(String[] args)throws Exception {
        SwingUtilities.invokeAndWait(()->{try{run();}catch(Exception failure){throw new RuntimeException(failure);}});
        System.out.println("PASS: completion arrow visible travel and dirty-layer rendering");System.exit(0);
    }
    private static void run()throws Exception {
        Rectangle visible=new Rectangle(0,44,700,500);
        for(Rectangle button:new Rectangle[]{new Rectangle(300,240,340,58),new Rectangle(300,510,340,58),new Rectangle(300,-100,340,58)}) {
            Point[] path=QuizPanel.completionPath(visible,button,new Rectangle(22,900,150,20));
            require(path!=null&&visible.contains(path[0])&&visible.contains(path[1]),"offscreen geometry cancelled the arrow");
            require(path[1].y-path[0].y>=96,"visible arrow travel is too short");
        }
        QuizPanel panel=new QuizPanel();panel.setSize(760,900);layout(panel);
        JLayer<?> layer=(JLayer<?>)get(panel,"completionLayer");
        BufferedImage base=new BufferedImage(layer.getWidth(),layer.getHeight(),BufferedImage.TYPE_INT_RGB);
        Graphics2D g=base.createGraphics();layer.paint(g);g.dispose();
        Object arrow=get(panel,"completionArrow");
        Point origin=SwingUtilities.convertPoint(layer,0,0,panel);
        set(arrow,"from",new Point(500,origin.y+180));set(arrow,"to",new Point(160,origin.y+440));
        set(arrow,"clip",new Rectangle(0,origin.y,layer.getWidth(),layer.getHeight()));
        set(arrow,"progress",.55);
        Timer timer=(Timer)get(arrow,"timer");timer.start();
        try {
            Method point=arrow.getClass().getDeclaredMethod("point",double.class);point.setAccessible(true);
            Point at=(Point)point.invoke(arrow,.55);
            Rectangle dirty=new Rectangle(at.x-36,at.y-origin.y-36,72,72);
            BufferedImage frame=new BufferedImage(base.getWidth(),base.getHeight(),BufferedImage.TYPE_INT_RGB);
            g=frame.createGraphics();g.drawImage(base,0,0,null);g.setClip(dirty);layer.paint(g);g.dispose();
            int changed=0;
            for(int y=Math.max(0,dirty.y);y<Math.min(frame.getHeight(),dirty.y+dirty.height);y++)
                for(int x=Math.max(0,dirty.x);x<Math.min(frame.getWidth(),dirty.x+dirty.width);x++)
                    if(frame.getRGB(x,y)!=base.getRGB(x,y))changed++;
            require(changed>30,"the completion arrow is missing from a dirty-region repaint");
            javax.imageio.ImageIO.write(frame,"png",new java.io.File("/tmp/synesis-completion-arrow.png"));
        } finally {timer.stop();}
    }
    private static Object get(Object object,String name)throws Exception {
        Field field=object.getClass().getDeclaredField(name);field.setAccessible(true);return field.get(object);
    }
    private static void set(Object object,String name,Object value)throws Exception {
        Field field=object.getClass().getDeclaredField(name);field.setAccessible(true);field.set(object,value);
    }
    private static void layout(Container parent){parent.doLayout();for(Component child:parent.getComponents())if(child.isVisible()&&child instanceof Container nested)layout(nested);}
    private static void require(boolean value,String message){if(!value)throw new AssertionError(message);}
}
