package dev.synesis.poc.pdf;

import com.google.gson.JsonObject;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicLong;
import javax.swing.*;

/** Visible paint cost, bounded recent glyphs and immutable document during animation. No window/API. */
public final class SummaryStreamPaintPerformanceTest {
    public static void main(String[]args)throws Exception {
        SwingUtilities.invokeAndWait(()->{try {
            AtomicLong now=new AtomicLong(1_000_000);StudyHtmlPane pane=new StudyHtmlPane(true);
            SummaryStreamText stream=new SummaryStreamText(pane,now::get);
            String body="이전 내용은 다시 생성하거나 페이드하지 않아요. ".repeat(1000);
            stream.accept(body,"",16);stream.finish();stream.accept(body+"새로 도착한 글자만 배경색에서 나타나도록 그려요. ".repeat(8),"",16);
            pane.setSize(646,Short.MAX_VALUE);pane.setSize(646,pane.getPreferredSize().height);pane.doLayout();
            int top=Math.max(0,pane.getHeight()-450);BufferedImage canvas=new BufferedImage(646,450,BufferedImage.TYPE_INT_RGB);
            var document=pane.getDocument();long revision=pane.contentRevision();ArrayList<Double> times=new ArrayList<>();
            now.addAndGet(140_000_000);
            for(int frame=0;frame<220;frame++) {
                Graphics2D g=canvas.createGraphics();g.setColor(Color.WHITE);g.fillRect(0,0,646,450);g.translate(0,-top);g.setClip(0,top,646,450);
                long started=System.nanoTime();pane.paint(g);long elapsed=System.nanoTime()-started;g.dispose();
                if(frame>=20)times.add(elapsed/1e6);
            }
            check(stream.recentGlyphs()<=SummaryStreamText.MAX_FADING_GLYPHS,"unbounded glyph animation");
            check(pane.getDocument()==document&&pane.contentRevision()==revision,"paint changed the document");
            times.sort(Double::compare);JsonObject result=new JsonObject();result.addProperty("documentCharacters",document.getLength());
            result.addProperty("visibleViewportWidth",646);result.addProperty("visibleViewportHeight",450);result.addProperty("paintFrames",times.size());
            result.addProperty("meanPaintMs",times.stream().mapToDouble(Double::doubleValue).average().orElseThrow());
            result.addProperty("p95PaintMs",times.get((int)(times.size()*.95)));result.addProperty("maximumFadingGlyphs",SummaryStreamText.MAX_FADING_GLYPHS);
            result.addProperty("documentEditsDuringPaint",pane.contentRevision()-revision);result.addProperty("nativeWindowsFpsMeasured",false);
            Files.writeString(Path.of("build/pdf-stream-motion-20261022/paint-performance.json"),result.toString());System.out.println(result);
        }catch(Exception error){throw new RuntimeException(error);}});System.exit(0);
    }
    private static void check(boolean condition,String why){if(!condition)throw new AssertionError(why);}
}
