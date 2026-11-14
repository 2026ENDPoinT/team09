package dev.synesis.poc.pdf;

import javax.swing.Icon;
import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.image.BufferedImage;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.util.Arrays;

/** Bright picker glyphs remain recognizable on white, with only cached image blits on repaint. */
public final class FolderGlyphContrastTest {
    public static void main(String[] args) throws Exception {
        Class<?> type=Class.forName(PdfLibraryPanel.class.getName()+"$FolderGlyph");
        Constructor<?> create=type.getDeclaredConstructor(String.class,Color.class,int.class);create.setAccessible(true);
        Field pixels=type.getDeclaredField("image");pixels.setAccessible(true);
        Field choices=PdfLibraryPanel.class.getDeclaredField("FOLDER_ICONS");choices.setAccessible(true);
        int checked=0;
        for(String[] choice:(String[][])choices.get(null)) {
            String kind=choice[0].equals("folder")?"none":choice[0];
            Icon icon=(Icon)create.newInstance(kind,Color.WHITE,33);
            BufferedImage cached=(BufferedImage)pixels.get(icon);
            int[] original=cached.getRGB(0,0,cached.getWidth(),cached.getHeight(),null,0,cached.getWidth());
            int whites=0;
            for(int rgb:original)if((rgb>>>24)>200&&(rgb&0xffffff)==0xffffff)whites++;
            check(whites>8,kind+": white foreground must keep its chosen color");
            BufferedImage painted=paint(icon,Color.WHITE);
            int visible=0;
            for(int y=0;y<33;y++)for(int x=0;x<33;x++) {
                int rgb=painted.getRGB(x,y);
                if(((rgb>>16)&255)<220&&((rgb>>8)&255)<220&&(rgb&255)<220)visible++;
            }
            check(visible>=8,kind+": missing readable shadow on white");
            Icon same=(Icon)create.newInstance(kind,Color.WHITE,33);
            check(pixels.get(same)==cached,kind+": opening picker regenerated cached shadow");
            for(int i=0;i<8;i++)paint(icon,Color.WHITE);
            check(pixels.get(icon)==cached&&Arrays.equals(original,
                cached.getRGB(0,0,cached.getWidth(),cached.getHeight(),null,0,cached.getWidth())),
                kind+": repaint changed or rebuilt shadow pixels");
            checked++;
        }
        Icon dark=(Icon)create.newInstance("music",Color.BLACK,33);
        BufferedImage onDark=paint(dark,Color.BLACK);
        int visible=0;
        for(int y=0;y<33;y++)for(int x=0;x<33;x++)if((onDark.getRGB(x,y)&255)>40)visible++;
        check(visible>=8,"dark glyphs must retain light shadow for dark backgrounds");
        System.out.println("FolderGlyphContrastTest passed: "+checked+" bright picker glyphs, dark-glyph fallback, cached image reuse.");
    }

    private static BufferedImage paint(Icon icon,Color background) {
        BufferedImage image=new BufferedImage(33,33,BufferedImage.TYPE_INT_RGB);
        Graphics2D graphics=image.createGraphics();
        try {graphics.setColor(background);graphics.fillRect(0,0,33,33);icon.paintIcon(null,graphics,0,0);}
        finally {graphics.dispose();}
        return image;
    }

    private static void check(boolean condition,String message) {if(!condition)throw new AssertionError(message);}
}
