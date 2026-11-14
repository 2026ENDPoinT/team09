package dev.synesis.poc.pdf;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import dev.synesis.poc.ui.StudyTheme;

import javax.swing.*;
import javax.swing.border.EmptyBorder;
import java.awt.*;
import java.awt.event.MouseAdapter;
import java.awt.event.MouseEvent;
import java.awt.image.BufferedImage;
import java.io.IOException;
import java.util.function.IntConsumer;

/** A source-bound crop module. The model chooses a region ID; PDF coordinates come from the local index. */
final class SlideLens {
    static final String ID = "synesis.slide-lens";
    record Request(String regionId, int page, double[] box, boolean paddingApplied, boolean fullPage) {
        Request(String id,int page,double[] box){this(id,page,box,false,false);}
    }

    private SlideLens() {}

    static Request resolve(JsonObject value, JsonObject index) {
        if (value == null || index == null || !ID.equals(PdfWorkspace.str(value, "moduleId"))) return null;
        try {
            if (value.get("schemaVersion").getAsInt() != 1) return null;
            int page = value.get("page").getAsInt();
            JsonArray pages = index.getAsJsonArray("pages");
            if (page < 1 || page > pages.size()) return null;
            JsonObject saved = pages.get(page - 1).getAsJsonObject();
            String id = PdfWorkspace.str(value, "regionId");
            if (saved.has("slideLensRegions") && saved.get("slideLensRegions").isJsonArray())
                for (var item : saved.getAsJsonArray("slideLensRegions")) {
                    JsonObject region = item.getAsJsonObject();
                    if (id.equals(PdfWorkspace.str(region,"regionId")) || id.equals(PdfWorkspace.str(region,"legacyId"))) {
                        if("page-vision-v1".equals(PdfWorkspace.str(region,"origin")) && "none".equals(PdfWorkspace.str(region,"lensReason")))return null;
                        Request request=verifiedRequest(value,id,page,PdfWorkspace.str(region,"kind"),region.getAsJsonArray("bbox"));
                        return request==null?null:new Request(id,page,request.box,
                            region.has("paddingApplied") && region.get("paddingApplied").getAsBoolean(),
                            "full_page".equals(PdfWorkspace.str(region,"locationState")));
                    }
                }
            // Older saved summaries used position-based IDs. Keep them readable after the catalog upgrade.
            for (String kind : new String[]{"image", "table", "text"}) {
                String field = switch(kind) { case "image" -> "imageRegions"; case "table" -> "tableRegions"; default -> "textRegions"; };
                if (!saved.has(field) || !saved.get(field).isJsonArray()) continue;
                JsonArray regions = saved.getAsJsonArray(field);
                for (int number = 0; number < regions.size(); number++) {
                    if (!id.equals("p" + page + "-" + kind + "-" + number)) continue;
                    return verifiedRequest(value,id,page,kind,regions.get(number).getAsJsonObject().getAsJsonArray("bbox"));
                }
            }
        } catch (RuntimeException ignored) { return null; }
        return null;
    }

    private static Request verifiedRequest(JsonObject value,String id,int page,String kind,JsonArray coordinates) {
        if(!kind.equals(PdfWorkspace.str(value,"kind")) || coordinates == null || coordinates.size()!=4)return null;
        double[] box=new double[4];
        for(int i=0;i<4;i++)box[i]=coordinates.get(i).getAsDouble();
        if(!Double.isFinite(box[0]) || !Double.isFinite(box[1]) || !Double.isFinite(box[2]) || !Double.isFinite(box[3])
                || box[0]<0 || box[1]<0 || box[2]>1 || box[3]>1 || box[0]>=box[2] || box[1]>=box[3])return null;
        JsonArray supplied=value.getAsJsonArray("bbox");
        if(supplied==null || supplied.size()!=4)return null;
        for(int i=0;i<4;i++)if(Math.abs(supplied.get(i).getAsDouble()-box[i])>.00001)return null;
        return new Request(id,page,box);
    }

    static BufferedImage crop(PdfSource source, Request request) throws IOException {
        BufferedImage page = source.render(request.page, 2.0f);
        double[] box = request.box;
        double margin=request.paddingApplied?0:.012;
        int left = Math.max(0, (int)Math.floor((box[0] - margin) * page.getWidth()));
        int top = Math.max(0, (int)Math.floor((box[1] - margin) * page.getHeight()));
        int right = Math.min(page.getWidth(), (int)Math.ceil((box[2] + margin) * page.getWidth()));
        int bottom = Math.min(page.getHeight(), (int)Math.ceil((box[3] + margin) * page.getHeight()));
        if (right - left < 8 || bottom - top < 8) throw new IOException("선택 영역이 너무 작습니다.");
        BufferedImage result = new BufferedImage(right - left, bottom - top, BufferedImage.TYPE_INT_RGB);
        Graphics2D graphics = result.createGraphics();
        try { graphics.drawImage(page, 0, 0, result.getWidth(), result.getHeight(), left, top, right, bottom, null); }
        finally { graphics.dispose(); }
        double pixels = (double)result.getWidth() * result.getHeight();
        if (pixels > 2_500_000) {
            double factor = Math.sqrt(2_500_000 / pixels);
            int width = Math.max(1, (int)Math.round(result.getWidth() * factor));
            int height = Math.max(1, (int)Math.round(result.getHeight() * factor));
            BufferedImage reduced = new BufferedImage(width, height, BufferedImage.TYPE_INT_RGB);
            Graphics2D scaled = reduced.createGraphics();
            try {
                scaled.setRenderingHint(RenderingHints.KEY_INTERPOLATION, RenderingHints.VALUE_INTERPOLATION_BICUBIC);
                scaled.drawImage(result, 0, 0, width, height, null);
            } finally { scaled.dispose(); }
            return reduced;
        }
        return result;
    }

    static final class Panel extends JPanel {
        Panel(Request request, BufferedImage image, String error, boolean expanded, int width,
              Runnable toggle, IntConsumer resize) {
            super();
            setLayout(new BoxLayout(this, BoxLayout.Y_AXIS));
            setBackground(Color.WHITE);
            setBorder(new EmptyBorder(5, 22, 10, 22));
            JButton button = new JButton(expanded ? "이해를 돕기 위한 강의 교안 닫기 ▲" : "이해를 돕기 위한 강의 교안 펼치기 ▼");
            button.setAlignmentX(Component.LEFT_ALIGNMENT);
            button.setForeground(StudyTheme.ACCENT);
            button.setBackground(new Color(0xf3f5f8));
            button.setBorder(new EmptyBorder(8, 10, 8, 10));
            button.setFocusPainted(false);
            button.addActionListener(event -> toggle.run());
            add(button);
            if (expanded) {
                JLabel source = new JLabel("PDF p." + request.page + (request.fullPage?" · 위치 확인을 위한 전체 페이지":" · 여백을 포함한 교안 영역"));
                source.setForeground(new Color(0x727986));
                source.setBorder(new EmptyBorder(7, 2, 5, 0));
                source.setAlignmentX(Component.LEFT_ALIGNMENT);
                add(source);
                if (image == null) {
                    JLabel loading = new JLabel(error == null ? "교안 영역을 불러오는 중…" : error);
                    loading.setBorder(new EmptyBorder(10, 2, 10, 0));
                    loading.setAlignmentX(Component.LEFT_ALIGNMENT);
                    add(loading);
                } else {
                    JPanel row = new JPanel(new FlowLayout(FlowLayout.LEFT, 0, 0));
                    row.setBackground(Color.WHITE);
                    row.setAlignmentX(Component.LEFT_ALIGNMENT);
                    row.add(new ResizeCanvas(image, width, resize));
                    add(row);
                    JLabel hint = new JLabel("그림 오른쪽 아래를 끌어 크기 조절");
                    hint.setForeground(new Color(0x727986));
                    hint.setBorder(new EmptyBorder(4, 2, 0, 0));
                    hint.setAlignmentX(Component.LEFT_ALIGNMENT);
                    add(hint);
                }
            }
        }

        @Override public Dimension getMaximumSize() { return new Dimension(Integer.MAX_VALUE, getPreferredSize().height); }
    }

    private static final class ResizeCanvas extends JComponent {
        private final BufferedImage image;
        private int width;
        private int startX, startWidth;
        private boolean dragging;

        ResizeCanvas(BufferedImage image, int width, IntConsumer resized) {
            this.image = image;
            this.width = Math.max(140, Math.min(1200, width));
            MouseAdapter mouse = new MouseAdapter() {
                private boolean edge(MouseEvent event) {
                    return event.getX() >= getWidth() - 24 && event.getY() >= getHeight() - 24;
                }
                @Override public void mouseMoved(MouseEvent event) {
                    setCursor(Cursor.getPredefinedCursor(edge(event) ? Cursor.SE_RESIZE_CURSOR : Cursor.DEFAULT_CURSOR));
                }
                @Override public void mousePressed(MouseEvent event) {
                    dragging = edge(event);
                    if (dragging) { startX = event.getXOnScreen(); startWidth = ResizeCanvas.this.width; }
                }
                @Override public void mouseDragged(MouseEvent event) {
                    if (!dragging) return;
                    int available = getParent() == null ? 1200 : Math.max(140, getParent().getWidth() - 8);
                    ResizeCanvas.this.width = Math.max(140, Math.min(Math.min(1200, available), startWidth + event.getXOnScreen() - startX));
                    revalidate(); repaint();
                }
                @Override public void mouseReleased(MouseEvent event) {
                    if (dragging) { dragging = false; resized.accept(ResizeCanvas.this.width); }
                }
            };
            addMouseListener(mouse); addMouseMotionListener(mouse);
        }

        @Override public Dimension getPreferredSize() {
            return new Dimension(width + 2, (int)Math.round(width * (double)image.getHeight() / image.getWidth()) + 2);
        }
        @Override protected void paintComponent(Graphics canvas) {
            Graphics2D graphics = (Graphics2D)canvas.create();
            try {
                graphics.setRenderingHint(RenderingHints.KEY_INTERPOLATION, RenderingHints.VALUE_INTERPOLATION_BILINEAR);
                graphics.drawImage(image, 1, 1, getWidth() - 2, getHeight() - 2, null);
                graphics.setColor(new Color(0xc5ccd7));
                graphics.drawRect(0, 0, getWidth() - 1, getHeight() - 1);
                graphics.setColor(StudyTheme.ACCENT);
                int x = getWidth() - 5, y = getHeight() - 5;
                graphics.drawLine(x - 10, y, x, y - 10);
                graphics.drawLine(x - 5, y, x, y - 5);
            } finally { graphics.dispose(); }
        }
    }
}
