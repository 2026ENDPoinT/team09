package dev.synesis.poc.pdf;

import java.awt.*;
import java.awt.image.BufferedImage;
import java.nio.file.*;
import java.util.concurrent.atomic.AtomicLong;
import javax.imageio.ImageIO;
import javax.swing.*;

/** Geometry and actual native glyph pixels, with a deterministic clock and no API/window. */
public final class SummaryStreamMotionTest {
    public static void main(String[] args)throws Exception {
        SwingUtilities.invokeAndWait(()->{try{spaces();glyphs();}catch(Exception error){throw new RuntimeException(error);}});
        System.out.println("PASS: reserved footprint absorbs wrapping, replenishes smoothly, missing-unit gap collapses, glyph fade edits no document, Unicode and append bounds");System.exit(0);
    }
    private static void spaces(){
        AtomicLong now=new AtomicLong(1_000_000);SummaryStreamSpace space=new SummaryStreamSpace(now::get);
        space.configure(true,true,16);space.measured(120);int initial=space.height();
        check(initial==0,"new spare space jumped instead of animating");
        now.addAndGet(SummaryStreamSpace.MOTION_NANOS/2);space.tick(now.get());int middle=space.height();
        check(middle>0&&middle<100,"spare space did not grow through intermediate heights");
        now.addAndGet(SummaryStreamSpace.MOTION_NANOS/2);space.tick(now.get());check(space.height()==100,"draft did not reserve four lines");
        int footprint=space.footprint();space.measured(145);
        check(space.footprint()==footprint&&space.height()==75,"a new wrapped line pushed later content instead of consuming its own spare");
        space.measured(180);check(space.footprint()==footprint,"replenishment jumped immediately");
        now.addAndGet(SummaryStreamSpace.MOTION_NANOS);space.tick(now.get());check(space.height()==100,"spare was not replenished before exhaustion");
        space.configure(false,true,16);check(space.height()==100,"completion snapped the current spare away");
        now.addAndGet(SummaryStreamSpace.MOTION_NANOS);space.tick(now.get());check(space.height()==50,"missing unit 2 did not retain a small gap before unit 3");
        space.configure(false,false,16);check(space.height()==50,"unit 2 arrival snapped the spare away");
        now.addAndGet(SummaryStreamSpace.MOTION_NANOS/2);space.tick(now.get());check(space.height()>0&&space.height()<50,"gap did not shrink through intermediate heights");
        now.addAndGet(SummaryStreamSpace.MOTION_NANOS/2);space.tick(now.get());check(space.height()==0&&!space.moving(),"unneeded gap did not disappear");
        SummaryStreamSpace resized=new SummaryStreamSpace(now::get);resized.configure(true,true,16);
        resized.measured(3000,1);resized.settle();resized.measured(100,646);
        check(resized.height()==100&&resized.footprint()==200,"a narrow initial measurement leaked a giant blank region after resize");
    }
    private static void glyphs()throws Exception {
        AtomicLong now=new AtomicLong(1_000_000);StudyHtmlPane pane=new StudyHtmlPane(true);
        SummaryStreamText text=new SummaryStreamText(pane,now::get);
        text.accept("가나다라 스트리밍 글자가 배경색에서 나타나요.","",18);var original=pane.getDocument();
        pane.setSize(640,200);pane.doLayout();long revision=pane.contentRevision();
        BufferedImage first=paint(pane);now.addAndGet(100_000_000);BufferedImage middle=paint(pane);
        now.addAndGet(300_000_000);BufferedImage done=paint(pane);
        check(ink(first)<ink(middle)&&ink(middle)<ink(done),"paint did not blend each arriving glyph from its background");
        check(pane.contentRevision()==revision&&pane.getDocument()==original,"animation rewrote/reparsed the document");
        Path out=Path.of("build/pdf-stream-motion-20261022");Files.createDirectories(out);
        ImageIO.write(first,"png",out.resolve("glyph-first.png").toFile());ImageIO.write(middle,"png",out.resolve("glyph-middle.png").toFile());ImageIO.write(done,"png",out.resolve("glyph-complete.png").toFile());
        String prefix="Text <script>literal</script> · 😀 한글 é";text.accept(prefix,"",16);long before=text.insertedCharacters();
        for(int i=0;i<100;i++){prefix+=" 추가";text.accept(prefix,"",16);}
        check(pane.getDocument()==original,"append recreated the document");
        check(text.insertedCharacters()-before==300,"append reinserted the old prefix");
        check(pane.getDocument().getText(0,pane.getDocument().getLength()).equals(prefix),"preview lost literal markup, Unicode, or appended text");
        check(text.recentGlyphs()<=SummaryStreamText.MAX_FADING_GLYPHS,"animation memory grows with the full answer");
        now.addAndGet(500_000_000);check(!text.active(now.get()),"glyph motion never stopped");
    }
    private static BufferedImage paint(JComponent pane){
        BufferedImage image=new BufferedImage(pane.getWidth(),pane.getHeight(),BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();
        g.setColor(Color.WHITE);g.fillRect(0,0,image.getWidth(),image.getHeight());pane.paint(g);g.dispose();return image;
    }
    private static long ink(BufferedImage image){long total=0;for(int y=0;y<image.getHeight();y++)for(int x=0;x<image.getWidth();x++)total+=255-(image.getRGB(x,y)&255);return total;}
    private static void check(boolean condition,String reason){if(!condition)throw new AssertionError(reason);}
}
