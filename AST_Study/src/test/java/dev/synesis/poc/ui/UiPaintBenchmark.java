package dev.synesis.poc.ui;

import javax.imageio.ImageIO;
import javax.swing.*;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.file.*;
import java.util.Arrays;
import java.util.Locale;

/** Repeatable CPU painting baseline. No window, user data, audio or network requests. */
public final class UiPaintBenchmark {
    public static void main(String[] args)throws Exception {
        Path output=Path.of(args.length==0?"build/ui-paint-benchmark":args[0]);Files.createDirectories(output);
        StringBuilder report=new StringBuilder("[\n");
        SwingUtilities.invokeAndWait(()->{try {
            LoginPanel panel=new LoginPanel(()->{});panel.setSize(1360,850);layout(panel);
            Field paperField=LoginPanel.class.getDeclaredField("paper");paperField.setAccessible(true);
            Object paper=paperField.get(panel);
            Method pointer=paper.getClass().getDeclaredMethod("followPointer",Point.class);pointer.setAccessible(true);
            Method update=paper.getClass().getDeclaredMethod("updateDots",double.class);update.setAccessible(true);
            boolean first=true;
            for(double scale:new double[]{1,1.25,1.5,2}) {
                BufferedImage canvas=new BufferedImage((int)Math.ceil(1360*scale),(int)Math.ceil(850*scale),BufferedImage.TYPE_INT_RGB);
                Graphics2D g=canvas.createGraphics();g.scale(scale,scale);double[] elapsed=new double[90];
                try {
                    for(int frame=-15;frame<elapsed.length;frame++) {
                        pointer.invoke(paper,new Point(150+(frame+15)*8,350));update.invoke(paper,1/60d);
                        long start=System.nanoTime();panel.printAll(g);
                        if(frame>=0)elapsed[frame]=(System.nanoTime()-start)/1e6;
                    }
                    panel.printAll(g);
                } finally {g.dispose();}
                Arrays.sort(elapsed);
                String row=String.format(Locale.ROOT,"{\"case\":\"login-full-repaint\",\"scale\":%.2f,\"medianMs\":%.3f,\"p95Ms\":%.3f,\"scope\":\"offscreen CPU paint; not screen FPS\"}",
                    scale,elapsed[elapsed.length/2],elapsed[(int)Math.floor((elapsed.length-1)*.95)]);
                if(!first)report.append(",\n");first=false;report.append(row);System.out.println(row);
                ImageIO.write(canvas,"png",output.resolve("login-"+scale+".png").toFile());
            }
        }catch(Exception e){throw new RuntimeException(e);}});
        report.append("\n]\n");Files.writeString(output.resolve("paint-times.json"),report);System.exit(0);
    }
    private static void layout(Container container){container.doLayout();for(Component child:container.getComponents())if(child instanceof Container nested)layout(nested);}
}
