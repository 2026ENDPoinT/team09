package dev.synesis.poc.pdf;

import java.awt.Color;
import java.awt.Component;
import java.awt.Container;
import java.awt.Graphics2D;
import java.awt.image.BufferedImage;
import java.util.Arrays;
import java.util.EnumMap;
import java.util.Locale;
import javax.swing.JComponent;
import javax.swing.JToggleButton;
import javax.swing.SwingUtilities;

/** Repeatable offscreen paint measurements; never opens a window or calls a provider. */
public final class QuizPaintPerformanceTest {
    private static final int WARMUP=35,SAMPLES=160;

    public static void main(String[] args) throws Exception {
        SwingUtilities.invokeAndWait(()->{
            QuizBookPreview cover=new QuizBookPreview();
            measure("book-concept-1x",cover,300,360,1);
            measure("book-concept-2x",cover,300,360,2);
            cover.setSelection(QuizPanel.Theme.PRACTICE,"상",17,false);
            measure("book-practice-1x",cover,300,360,1);
            measure("book-practice-2x",cover,300,360,2);
            EnumMap<QuizPanel.Theme,JToggleButton> buttons=new EnumMap<>(QuizPanel.Theme.class);
            QuizModeSelector selector=new QuizModeSelector(buttons,ignored->{});
            selector.select(QuizPanel.Theme.PRACTICE,false);
            measure("selector-practice-2x",selector,716,77,2);
            QuizPanel panel=new QuizPanel();panel.reset(24,"paint-fixture");panel.setReady(true);
            panel.setGenerationRequestHandler(ignored->{});panel.setGenerationReady(true);
            panel.themeButtons.get(QuizPanel.Theme.PRACTICE).doClick();
            measure("page-practice-2x",panel,760,1000,2);
            java.util.List<QuizQuestion> questions=new java.util.ArrayList<>();
            for(int i=0;i<120;i++)questions.add(new QuizQuestion("q"+i,"paint-fixture",QuizQuestion.Type.OX,"함수의 극한",
                "함수의 극한은 $\\lim_{x \\to a}f(x)=L$로 표현할 수 있어요.",java.util.List.of(),"O",
                "입력값이 주어진 점에 가까워질 때 함숫값이 일정한 값에 가까워지는지를 확인해요.",java.util.List.of(),java.util.List.of(),false));
            panel.showQuestions(questions);measure("solve-120-single-card-2x",panel,760,1000,2);
            panel.cards.getFirst().choiceButtons.get("O").doClick(0);panel.cards.getFirst().checkButton.doClick(0);
            measure("solve-120-graded-2x",panel,760,1000,2);panel.reset(0,"");
            coverMetadataAndStableNormalPaint();
        });
        System.out.println("QuizPaintPerformanceTest OK: offscreen timing, nonempty covers and live cover metadata. No windows or paid calls.");
        System.exit(0);
    }

    private static void measure(String name,JComponent component,int width,int height,int scale) {
        component.setSize(width,height);
        for(int i=0;i<6;i++){component.invalidate();layout(component);}
        BufferedImage canvas=new BufferedImage(width*scale,height*scale,BufferedImage.TYPE_INT_ARGB_PRE);
        Graphics2D g=canvas.createGraphics();g.scale(scale,scale);
        try {
            for(int i=0;i<WARMUP;i++){clear(g,width,height);component.printAll(g);}
            long[] times=new long[SAMPLES];
            for(int i=0;i<SAMPLES;i++) {
                clear(g,width,height);long started=System.nanoTime();component.printAll(g);times[i]=System.nanoTime()-started;
            }
            Arrays.sort(times);
            System.out.printf(Locale.ROOT,"%s median_ms=%.3f p95_ms=%.3f samples=%d%n",name,
                times[SAMPLES/2]/1_000_000d,times[(int)(SAMPLES*.95)]/1_000_000d,SAMPLES);
            if(nonwhite(canvas)<100)throw new AssertionError(name+" rendered no meaningful content");
        } finally {g.dispose();}
    }

    private static void coverMetadataAndStableNormalPaint() {
        QuizBookPreview cover=new QuizBookPreview();cover.setSize(300,360);
        BufferedImage before=paint(cover);
        cover.setSelection(QuizPanel.Theme.RECALL,"최상",23,false);
        BufferedImage after=paint(cover),again=paint(cover);
        String description=cover.getAccessibleContext().getAccessibleDescription();
        if(!description.contains("암기 확인")||!description.contains("최상")||!description.contains("23문제"))
            throw new AssertionError("cover metadata is stale");
        if(Arrays.equals(pixels(before),pixels(after)))throw new AssertionError("theme change did not redraw the cover");
        if(!Arrays.equals(pixels(after),pixels(again)))throw new AssertionError("static cover changes during idle repaints");
        cover.setSelection(QuizPanel.Theme.RECALL,"중",7,false);
        if(Arrays.equals(pixels(after),pixels(paint(cover))))throw new AssertionError("setting change did not update cover text");
    }

    private static BufferedImage paint(JComponent component) {
        BufferedImage canvas=new BufferedImage(component.getWidth(),component.getHeight(),BufferedImage.TYPE_INT_ARGB_PRE);
        Graphics2D g=canvas.createGraphics();try{clear(g,canvas.getWidth(),canvas.getHeight());component.printAll(g);}finally{g.dispose();}
        return canvas;
    }
    private static int[] pixels(BufferedImage image){return image.getRGB(0,0,image.getWidth(),image.getHeight(),null,0,image.getWidth());}
    private static int nonwhite(BufferedImage image){int count=0;for(int pixel:pixels(image))if((pixel&0xffffff)!=0xffffff)count++;return count;}
    private static void clear(Graphics2D g,int width,int height){g.setColor(Color.WHITE);g.fillRect(0,0,width,height);}
    private static void layout(Container parent){parent.doLayout();for(Component child:parent.getComponents())if(child instanceof Container nested)layout(nested);}
}
