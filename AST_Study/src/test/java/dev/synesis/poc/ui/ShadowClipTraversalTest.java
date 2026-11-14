package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;
import java.awt.image.BufferedImage;

/** Clipped shadow painting must match a full repaint without walking distant card descendants. */
public final class ShadowClipTraversalTest {
    private static final class Probe extends JPanel {
        int visits;
        @Override public Component[] getComponents(){visits++;return super.getComponents();}
    }
    public static void main(String[] args)throws Exception{
        SwingUtilities.invokeAndWait(()->{
            JPanel content=new JPanel(null);content.setBackground(Color.WHITE);
            JPanel near=new MistWorkspaceTheme.Panel(null,12,Color.WHITE,null);near.setBounds(30,30,200,180);content.add(near);
            Probe distant=new Probe();distant.setLayout(null);distant.setBounds(30,400,200,180);
            for(int i=0;i<400;i++)distant.add(new JLabel("fixture"));content.add(distant);
            JLayer<JComponent> layer=MistWorkspaceTheme.shadows(content);layer.setSize(500,650);layer.doLayout();
            BufferedImage full=new BufferedImage(500,650,BufferedImage.TYPE_INT_ARGB),clipped=new BufferedImage(500,650,BufferedImage.TYPE_INT_ARGB);
            try{
                Graphics2D g=full.createGraphics();layer.paint(g);g.dispose();distant.visits=0;
                Rectangle clip=new Rectangle(18,18,235,215);g=clipped.createGraphics();g.setClip(clip);layer.paint(g);g.dispose();
                if(distant.visits!=0)throw new AssertionError("clipped repaint traversed distant descendants");
                for(int y=clip.y;y<clip.y+clip.height;y++)for(int x=clip.x;x<clip.x+clip.width;x++)
                    if(full.getRGB(x,y)!=clipped.getRGB(x,y))throw new AssertionError("clipped repaint differs at "+x+","+y);
            }finally{full.flush();clipped.flush();}
        });
        System.out.println("ShadowClipTraversalTest passed: clipped/full pixels match; distant 400-child subtree skipped");
    }
}
