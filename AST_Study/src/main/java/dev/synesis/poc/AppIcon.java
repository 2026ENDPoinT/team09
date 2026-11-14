package dev.synesis.poc;

import javax.imageio.ImageIO;
import java.awt.AlphaComposite;
import java.awt.Graphics2D;
import java.awt.Image;
import java.awt.RenderingHints;
import java.awt.Taskbar;
import java.awt.image.BufferedImage;
import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;

/** Figma's application tile, including its original transparency, glass layers and shadow. */
final class AppIcon {
    private AppIcon() {}

    static List<Image> windowSizes() {
        try (InputStream input = AppIcon.class.getResourceAsStream("synesis-logo.png")) {
            if (input == null) return List.of();
            BufferedImage logo = ImageIO.read(input);
            if (logo == null) return List.of();

            List<Image> sizes = new ArrayList<>();
            for (int size : new int[]{16, 20, 24, 32, 48, 64, 128, 256, 512, 1024}) {
                if (logo.getWidth() == size && logo.getHeight() == size) { sizes.add(logo); continue; }
                BufferedImage icon = new BufferedImage(size, size, BufferedImage.TYPE_INT_ARGB);
                Graphics2D small = icon.createGraphics();
                small.setComposite(AlphaComposite.Src);
                small.setRenderingHint(RenderingHints.KEY_INTERPOLATION, RenderingHints.VALUE_INTERPOLATION_BICUBIC);
                small.setRenderingHint(RenderingHints.KEY_RENDERING, RenderingHints.VALUE_RENDER_QUALITY);
                small.drawImage(logo, 0, 0, size, size, null);
                small.dispose();
                sizes.add(icon);
            }
            return sizes;
        } catch (IOException exception) {
            return List.of();
        }
    }

    static void installDockIcon() {
        if (!System.getProperty("os.name", "").toLowerCase().contains("mac")) return;
        List<Image> icons = windowSizes();
        if (icons.isEmpty()) return;
        try {
            if (!Taskbar.isTaskbarSupported()) return;
            Taskbar taskbar = Taskbar.getTaskbar();
            if (taskbar.isSupported(Taskbar.Feature.ICON_IMAGE)) {
                taskbar.setIconImage(icons.get(icons.size() - 1));
            }
        } catch (RuntimeException ignored) {
            // The app still starts if this JVM or desktop session cannot change its Dock icon.
        }
    }
}
