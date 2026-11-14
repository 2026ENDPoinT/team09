package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.MistWorkspaceTheme;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.util.Map;

/** Offline tile ownership check; no app window, user data or image export. */
public final class AssistantShadowCacheTest {
    public static void main(String[] args)throws Exception {
        BufferedImage surface=new BufferedImage(600,750,BufferedImage.TYPE_INT_ARGB);
        Graphics2D g=surface.createGraphics();
        try {
            Rectangle bounds=new Rectangle(30,30,460,640);
            MistWorkspaceTheme.paintAssistantShadow(g,bounds);
            if((surface.getRGB(27,350)>>>24)<40)throw new AssertionError("contact shadow too faint");
            // The shadow must meet the card without a bright gap or a displaced outline.
            for(int distance=1;distance<=12;distance++) {
                int left=surface.getRGB(bounds.x-distance,350)>>>24;
                int right=surface.getRGB(bounds.x+bounds.width-1+distance,350)>>>24;
                if(left==0||right==0||Math.abs(left-right)>3)throw new AssertionError("shadow does not align with card sides at "+distance+": "+left+" / "+right);
            }
            if((surface.getRGB(250,bounds.y+bounds.height)>>>24)==0)throw new AssertionError("gap below card");
            var field=MistWorkspaceTheme.class.getDeclaredField("SHADOW_PATCHES");field.setAccessible(true);
            Map<?,?> tiles=(Map<?,?>)field.get(null);Object original=tiles.get("assistant");int count=tiles.size();
            BufferedImage tile=(BufferedImage)original;
            if(tile.getWidth()!=160||tile.getHeight()!=160)throw new AssertionError("unbounded shadow buffer");
            for(int i=0;i<100;i++) {
                bounds.setBounds(30+i%10,30+i%12,200+i*2,250+i*3);
                MistWorkspaceTheme.paintAssistantShadow(g,bounds);
                if(tiles.get("assistant")!=original||tiles.size()!=count)throw new AssertionError("shadow rerasterized or cache grew");
            }
            System.out.println("AssistantShadowCacheTest OK · aligned edges without gaps · same 160×160 tile across 100 sizes/positions · 100 KiB pixel buffer");
        } finally {g.dispose();surface.flush();}
    }
}
