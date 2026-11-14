package dev.synesis.poc.pdf;

import java.awt.*;
import java.awt.image.BufferedImage;
import java.nio.file.*;
import java.util.*;
import javax.imageio.ImageIO;
import javax.swing.*;
import javax.swing.text.*;
import javax.swing.text.html.*;

/** Page chips must wrap as whole links within the overview, including their padding. */
public final class SummaryCitationWrapTest {
    public static void main(String[] args) throws Exception {
        SwingUtilities.invokeAndWait(() -> {
            try { run(); } catch (Exception e) { throw new RuntimeException(e); }
        });
        System.out.println("SummaryCitationWrapTest passed");
    }

    private static void run() throws Exception {
        StringBuilder links = new StringBuilder("<p class='muted'>근거 ");
        for (int page = 1; page <= 50; page++)
            links.append("<a href='page:").append(page).append("'>p.").append(page).append("</a> &nbsp; ");
        links.append("</p>");
        Path output = Path.of("build/summary-citation-wrap-20261017");
        Files.createDirectories(output);
        for (int font : new int[]{12, 16, 24, 28}) {
            StudyHtmlPane pane = new StudyHtmlPane(true);
            pane.setReadingSkin(true);
            pane.setEditable(false);
            pane.setText(SummarySkin.document("요약", "<div class='study-overview'><h2>이 강의의 흐름</h2>"
                + "<p>추상미술의 정신적·시대적 지향과 여러 작가의 색채와 관람 경험을 다뤄요.</p>"
                + links + "</div>", font));
            long revision = pane.contentRevision();
            for (int width : new int[]{800, 646, 340, 240, 480, 800}) {
                pane.setSize(width, Short.MAX_VALUE);
                pane.modelToView2D(pane.getDocument().getLength());
                pane.setSize(width, pane.getPreferredSize().height);
                BufferedImage image = new BufferedImage(width, pane.getHeight(), BufferedImage.TYPE_INT_RGB);
                Graphics2D graphics = image.createGraphics();
                graphics.setColor(Color.WHITE); graphics.fillRect(0, 0, width, image.getHeight());
                pane.paint(graphics); graphics.dispose();
                verifyViews(pane.getUI().getRootView(pane), new Rectangle(0, 0, width, pane.getHeight()), null);
                HTMLDocument doc = (HTMLDocument)pane.getDocument();
                int count = 0;
                for (HTMLDocument.Iterator it = doc.getIterator(HTML.Tag.A); it.isValid(); it.next()) {
                    var start = pane.modelToView2D(it.getStartOffset());
                    var end = pane.modelToView2D(it.getEndOffset() - 1);
                    check(Math.abs(start.getY() - end.getY()) < 1, "page link split across lines");
                    int hit = pane.viewToModel2D(new Point((int)start.getX() + 6, (int)start.getCenterY()));
                    check(hit >= it.getStartOffset() && hit < it.getEndOffset(), "page link hit testing lost");
                    check(("page:" + (++count)).equals(it.getAttributes().getAttribute(HTML.Attribute.HREF)),
                        "page link target changed");
                }
                check(count == 50, "page links lost");
                check(pane.contentRevision() == revision, "resize reparsed content");
                if (font == 16 && (width == 800 || width == 340))
                    ImageIO.write(image, "png", output.resolve("citations-" + width + ".png").toFile());
            }
        }
    }

    private static void verifyViews(View view, Shape allocation, Rectangle card) {
        if (view.getClass().getSimpleName().equals("CardView")) card = allocation.getBounds();
        if (view.getClass().getSimpleName().equals("CitationView") && card != null) {
            Rectangle chip = allocation.getBounds();
            check(chip.x >= card.x + 12 && chip.getMaxX() <= card.getMaxX() - 12,
                "citation padding overflowed card: chip=" + chip + ", card=" + card);
        }
        for (int i = 0; i < view.getViewCount(); i++) {
            Shape child = view.getChildAllocation(i, allocation);
            if (child != null) verifyViews(view.getView(i), child, card);
        }
    }
    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
