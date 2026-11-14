package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.Field;

/** Offscreen coverage, clipped repaint parity and bounded corner-cache reuse on a 2x display. */
public final class RoundedPanelEdgesTest {
    public static void main(String[] args)throws Exception{
        SwingUtilities.invokeAndWait(()->{
            MistWorkspaceTheme.Panel panel=new MistWorkspaceTheme.Panel(new BorderLayout(),12,Color.WHITE,MistWorkspaceTheme.LINE);
            JPanel opaque=new JPanel();opaque.setBackground(MistWorkspaceTheme.HEADER);panel.add(opaque);
            panel.setSize(160,120);panel.doLayout();
            BufferedImage old=paint(panel,null);
            panel.putClientProperty("mist.smoothCorners",true);BufferedImage full=paint(panel,null);
            int before=partial(old),after=partial(full);
            check(after>before,"corner edges still have binary coverage: "+before+" -> "+after);
            check((full.getRGB(0,0)>>>24)==0,"outside corner is not transparent");
            check((full.getRGB(160,120)>>>24)==255,"interior became translucent");
            Rectangle clip=new Rectangle(140,0,20,20);BufferedImage clipped=paint(panel,clip);
            for(int y=0;y<40;y++)for(int x=280;x<320;x++)
                check(clipped.getRGB(x,y)==full.getRGB(x,y),"clipped corner differs from full paint");
            Object renderer=get(panel,"smoothEdges");Object[] masks=((Object[])get(renderer,"masks")).clone();Object[] tiles=((Object[])get(renderer,"tiles")).clone();
            for(int i=0;i<30;i++){
                panel.setSize(160+i,120+i);panel.doLayout();BufferedImage frame=paint(panel,null);frame.flush();
                for(int corner=0;corner<4;corner++){
                    check(masks[corner]==((Object[])get(renderer,"masks"))[corner],"resize rebuilt corner masks");
                    check(tiles[corner]==((Object[])get(renderer,"tiles"))[corner],"resize reallocated corner buffers");
                }
            }
            old.flush();full.flush();clipped.flush();
            System.out.println("PASS RoundedPanelEdges: coverage pixels "+before+" -> "+after+"; clipped/full parity; resize reuses 4 small masks/buffers");
        });
    }
    private static BufferedImage paint(JComponent panel,Rectangle clip){
        BufferedImage image=new BufferedImage(panel.getWidth()*2,panel.getHeight()*2,BufferedImage.TYPE_INT_ARGB);
        Graphics2D g=image.createGraphics();try{g.scale(2,2);if(clip!=null)g.setClip(clip);panel.paint(g);}finally{g.dispose();}return image;
    }
    private static int partial(BufferedImage image){int count=0;for(int y=0;y<24;y++)for(int x=0;x<24;x++){int a=image.getRGB(x,y)>>>24;if(a>0&&a<255)count++;}return count;}
    private static Object get(Object o,String field){try{Field f=o.getClass().getDeclaredField(field);f.setAccessible(true);return f.get(o);}catch(Exception e){throw new RuntimeException(e);}}
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
}
