package dev.synesis.poc.pdf;

import java.awt.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;
import java.util.Arrays;
import javax.swing.*;

/** Offscreen dirty-paint and lifecycle checks; no application window or provider. */
public final class QuizGenerationShimmerTest {
    public static void main(String[] args)throws Exception {
        SwingUtilities.invokeAndWait(()->{try{run();}catch(Exception failure){throw new RuntimeException(failure);}});
        System.out.println("QuizGenerationShimmerTest OK: text-only change, clipped paint, hidden/completed/reduced-motion stop");
        System.exit(0);
    }
    private static void run()throws Exception {
        QuizPanel panel=new QuizPanel();
        JButton button=panel.generate;button.setSize(480,58);
        panel.setGenerating(true,"출제 배분 중");
        Timer motion=(Timer)field(button,"motion");
        require(!motion.isRunning(),"hidden generation retained an animation timer");
        Method bounds=button.getClass().getDeclaredMethod("textDamage");bounds.setAccessible(true);
        Rectangle dirty=(Rectangle)bounds.invoke(button);
        require(dirty.width<240&&dirty.height<40,"dirty region grew beyond the short label");
        BufferedImage first=paint(button,null,null);
        Thread.sleep(100);
        BufferedImage second=paint(button,null,null);
        int changed=0;
        for(int y=0;y<58;y++)for(int x=0;x<480;x++){
            if(first.getRGB(x,y)==second.getRGB(x,y))continue;
            require(dirty.contains(x,y),"shimmer changed the background or arrow");changed++;
        }
        require(changed>5,"generation text did not animate");
        BufferedImage partial=paint(button,first,dirty);
        for(int y=0;y<58;y++)for(int x=0;x<480;x++)
            if(!dirty.contains(x,y))require(partial.getRGB(x,y)==first.getRGB(x,y),"clipped paint touched outside label");

        String previous=System.getProperty("synesis.reduceMotion");
        try{
            System.setProperty("synesis.reduceMotion","true");
            Method update=button.getClass().getDeclaredMethod("updateMotion");update.setAccessible(true);
            motion.start();update.invoke(button);
            require(!motion.isRunning(),"reduced motion retained timer");
            BufferedImage still=paint(button,null,null);Thread.sleep(50);
            require(Arrays.equals(pixels(still),pixels(paint(button,null,null))),"reduced motion still animates");
        }finally{
            if(previous==null)System.clearProperty("synesis.reduceMotion");else System.setProperty("synesis.reduceMotion",previous);
        }
        motion.start();panel.setGenerating(false,"생성 완료");
        require(!motion.isRunning(),"completion retained timer");
        require(!button.getText().contains("생성 중"),"completion left stale generating label");
        motion.start();button.removeNotify();
        require(!motion.isRunning(),"removed component retained timer");
    }
    private static Object field(Object object,String name)throws Exception {
        Field field=object.getClass().getDeclaredField(name);field.setAccessible(true);return field.get(object);
    }
    private static BufferedImage paint(JButton button,BufferedImage base,Rectangle clip){
        BufferedImage image=new BufferedImage(480,58,BufferedImage.TYPE_INT_ARGB);
        Graphics2D g=image.createGraphics();
        try{if(base!=null)g.drawImage(base,0,0,null);if(clip!=null)g.setClip(clip);button.paint(g);}finally{g.dispose();}
        return image;
    }
    private static int[] pixels(BufferedImage image){return image.getRGB(0,0,480,58,null,0,480);}
    private static void require(boolean value,String message){if(!value)throw new AssertionError(message);}
}
