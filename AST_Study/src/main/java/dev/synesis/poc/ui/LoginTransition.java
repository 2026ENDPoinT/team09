package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;
import java.awt.event.HierarchyEvent;
import java.awt.event.KeyEvent;
import java.awt.event.MouseAdapter;
import java.awt.geom.AffineTransform;
import java.awt.geom.Ellipse2D;
import java.awt.image.BufferedImage;

/** Covers login/logout switches with a charcoal circular wipe. Runs on the EDT. */
public final class LoginTransition extends JPanel {
    private static final double FILL_MS = 760, HOLD_MS = 380, REVEAL_MS = 680;
    private static final Color CHARCOAL = new Color(0x242424);
    private static final Color SUBTITLE = new Color(0xdedede);
    private final JRootPane root;
    private final Component previousGlass;
    private final boolean previousVisible;
    private final Runnable enterHome;
    private final Point origin;
    private final String title, subtitle;
    private final boolean logout;
    private JButton nextDefaultButton;
    private final Timer timer;
    private long started;
    private BufferedImage departure, arrival;
    private AffineTransform snapshotToLogical = new AffineTransform();
    private int snapshotWidth, snapshotHeight;
    private double elapsed;
    private boolean entered, finished;

    static void play(JButton button, Runnable enterHome) {
        play(button, enterHome, "Approved", "환영합니다.", false);
    }

    public static void playLogout(JButton button, Runnable enterLogin) {
        play(button, enterLogin, "", "", true);
    }

    private static void play(JButton button, Runnable destination, String title, String subtitle, boolean logout) {
        JRootPane root = SwingUtilities.getRootPane(button);
        if (root == null) { destination.run(); return; }
        if (root.getGlassPane() instanceof LoginTransition) return;
        Point origin = SwingUtilities.convertPoint(button, button.getWidth() / 2,
            button.getHeight() / 2, root);
        LoginTransition transition = new LoginTransition(root, origin, destination, title, subtitle, logout);
        root.setDefaultButton(null);
        root.setGlassPane(transition);
        transition.setVisible(true);
        transition.requestFocusInWindow();
        transition.started = System.nanoTime();
        transition.timer.start();
    }

    private LoginTransition(JRootPane root, Point origin, Runnable enterHome, String title, String subtitle, boolean logout) {
        this.root = root;
        this.origin = origin;
        this.enterHome = enterHome;
        this.title = title;
        this.subtitle = subtitle;
        this.logout = logout;
        nextDefaultButton = root.getDefaultButton();
        previousGlass = root.getGlassPane();
        previousVisible = previousGlass.isVisible();
        // An opaque glass pane prevents Swing from repainting the live scene beneath it.
        departure = snapshot();
        pauseLogin(root.getContentPane(), true);
        setOpaque(true);
        setFocusable(true);
        setFocusTraversalKeysEnabled(false);
        enableEvents(AWTEvent.KEY_EVENT_MASK);
        MouseAdapter blockPointer = new MouseAdapter() {};
        addMouseListener(blockPointer);
        addMouseMotionListener(blockPointer);
        addMouseWheelListener(event -> event.consume());
        setCursor(Cursor.getPredefinedCursor(Cursor.WAIT_CURSOR));
        timer = new Timer(16, event -> advance());
        timer.setCoalesce(true);
        addHierarchyListener(event -> {
            if ((event.getChangeFlags() & HierarchyEvent.DISPLAYABILITY_CHANGED) != 0
                && !isDisplayable()) finish();
        });
        getAccessibleContext().setAccessibleName(logout ? "로그아웃 전환" : title + " · " + subtitle);
    }

    private BufferedImage snapshot() {
        JLayeredPane scene=root.getLayeredPane();
        GraphicsConfiguration config=root.getGraphicsConfiguration();
        var transform=config==null?new java.awt.geom.AffineTransform():config.getDefaultTransform();
        double sx=transform.getScaleX(),sy=transform.getScaleY();
        snapshotToLogical=AffineTransform.getScaleInstance(1/sx,1/sy);
        snapshotWidth=scene.getWidth();snapshotHeight=scene.getHeight();
        BufferedImage image=new BufferedImage(Math.max(1,(int)Math.ceil(scene.getWidth()*sx)),
            Math.max(1,(int)Math.ceil(scene.getHeight()*sy)),BufferedImage.TYPE_INT_RGB);
        Graphics2D g=image.createGraphics();
        RepaintManager manager=RepaintManager.currentManager(root);
        boolean buffered=manager.isDoubleBufferingEnabled();
        try {
            manager.setDoubleBufferingEnabled(false);
            g.scale(sx,sy);
            scene.paint(g);
        } finally {manager.setDoubleBufferingEnabled(buffered);g.dispose();}
        return image;
    }

    private static void pauseLogin(Component component,boolean paused) {
        if(component instanceof LoginPanel login)login.setAnimationPaused(paused);
        if(component instanceof Container container)
            for(Component child:container.getComponents())pauseLogin(child,paused);
    }

    @Override protected void processKeyEvent(KeyEvent event) { event.consume(); }

    private void advance() {
        if (finished) return;
        elapsed = (System.nanoTime() - started) / 1_000_000.0;
        if (!entered && elapsed >= FILL_MS) {
            entered = true;
            // The opaque wipe now covers every pixel; do not retain two full-screen snapshots.
            if (departure != null) departure.flush();
            departure = null;
            try {
                enterHome.run();
                if (finished || root.getGlassPane() != this) { finish(); return; }
                pauseLogin(root.getContentPane(),true);
                root.getLayeredPane().validate();
                if (finished) return;
                arrival=snapshot();
                if (finished) {
                    arrival.flush();
                    arrival=null;
                    return;
                }
                nextDefaultButton = root.getDefaultButton();
                root.setDefaultButton(null);
                requestFocusInWindow();
            }
            catch (RuntimeException | Error failure) { finish(); throw failure; }
        }
        if (elapsed >= FILL_MS + HOLD_MS + REVEAL_MS) finish();
        else repaint();
    }

    private void finish() {
        if (finished) return;
        finished = true;
        timer.stop();
        pauseLogin(root.getContentPane(),false);
        if (departure != null) departure.flush();
        if (arrival != null) arrival.flush();
        departure=arrival=null;
        if (root.getGlassPane() == this) {
            setVisible(false);
            root.setGlassPane(previousGlass);
            previousGlass.setVisible(previousVisible);
            root.setDefaultButton(nextDefaultButton);
            if (nextDefaultButton != null) nextDefaultButton.requestFocusInWindow();
            else root.getContentPane().requestFocusInWindow();
            root.repaint();
        }
    }

    @Override protected void paintComponent(Graphics graphics) {
        Graphics2D g = (Graphics2D) graphics.create();
        try {
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
            g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING, RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
            int w = getWidth(), h = getHeight();
            double fill = smooth(elapsed / FILL_MS);
            double reveal = smooth((elapsed - FILL_MS - HOLD_MS) / REVEAL_MS);
            float opacity = (float) (1 - reveal);
            double maxRadius = Math.hypot(Math.max(origin.x, w - origin.x),
                Math.max(origin.y, h - origin.y)) + 4;
            double r = 22 + maxRadius * fill;
            boolean filling = elapsed < FILL_MS;
            boolean covered = filling ? r >= maxRadius : opacity >= 1;
            if (covered) {
                // No scene blit while the solid wipe hides it, including the hold phase.
                g.setColor(CHARCOAL);
                g.fillRect(0,0,w,h);
            } else {
                BufferedImage scene=entered && arrival!=null?arrival:departure;
                if (scene != null) {
                    // Normal frames blit native pixels; resizing temporarily fits the frozen scene.
                    if(snapshotWidth==w && snapshotHeight==h)g.drawImage(scene,snapshotToLogical,null);
                    else g.drawImage(scene,0,0,w,h,null);
                } else {
                    g.setColor(CHARCOAL);
                    g.fillRect(0,0,w,h);
                }
            }
            if (elapsed < FILL_MS) {
                if (!covered) {
                    // One antialiased solid circle replaces the clipped full-screen image and ripples.
                    g.setColor(CHARCOAL);
                    g.fill(new Ellipse2D.Double(origin.x - r, origin.y - r, r * 2, r * 2));
                }
            } else if (!covered && opacity > 0) {
                g.setComposite(AlphaComposite.SrcOver.derive(opacity));
                g.setColor(CHARCOAL);
                g.fillRect(0,0,w,h);
            }

            float messageAlpha = (float) (smooth((elapsed - FILL_MS * .65) / 260) * opacity);
            if (messageAlpha <= 0) return;
            g.setComposite(AlphaComposite.SrcOver.derive(messageAlpha));
            int centerY = h / 2 + (int) (12 * (1 - smooth((elapsed - FILL_MS * .65) / 360)))
                - (int) (16 * reveal);
            g.setColor(Color.WHITE);
            g.setStroke(new BasicStroke(2.7f, BasicStroke.CAP_ROUND, BasicStroke.JOIN_ROUND));
            if (logout) {
                int x = w / 2, y = centerY - 60;
                // Open doorway and an outward arrow, drawn as vectors at the same icon size.
                g.drawLine(x + 1, y - 21, x - 20, y - 21);
                g.drawLine(x - 20, y - 21, x - 20, y + 21);
                g.drawLine(x - 20, y + 21, x + 1, y + 21);
                g.drawLine(x + 1, y - 21, x + 1, y - 12);
                g.drawLine(x + 1, y + 12, x + 1, y + 21);
                double exit = smooth((elapsed - FILL_MS * .78) / 700);
                Graphics2D arrow = (Graphics2D) g.create();
                try {
                    arrow.translate(25 * exit, 0);
                    arrow.setComposite(AlphaComposite.SrcOver.derive(
                        messageAlpha * (float) (1 - smooth((exit - .65) / .35))));
                    arrow.drawLine(x - 7, y, x + 22, y);
                    arrow.drawLine(x + 13, y - 9, x + 22, y);
                    arrow.drawLine(x + 22, y, x + 13, y + 9);
                } finally { arrow.dispose(); }
            } else {
                double iconTime = elapsed - FILL_MS * .65;
                double circle = smooth(iconTime / 320);
                double check = smooth((iconTime - 260) / 280);
                double pingTime = (iconTime - 480) / 360;
                double ping = pingTime > 0 && pingTime < 1 ? Math.sin(Math.PI * pingTime) : 0;
                Graphics2D icon = (Graphics2D) g.create();
                try {
                    icon.translate(w / 2.0, centerY - 60);
                    icon.scale(1 + .10 * ping, 1 + .10 * ping);
                    icon.draw(new java.awt.geom.Arc2D.Double(-22, -22, 44, 44,
                        90, -360 * circle, java.awt.geom.Arc2D.OPEN));
                    // Trace the short downstroke before completing the long upstroke.
                    double shortLength = Math.hypot(7, 7), longLength = Math.hypot(13, 14);
                    double traced = check * (shortLength + longLength);
                    java.awt.geom.Path2D mark = new java.awt.geom.Path2D.Double();
                    mark.moveTo(-9, 0);
                    double first = Math.min(1, traced / shortLength);
                    mark.lineTo(-9 + 7 * first, 7 * first);
                    if (traced > shortLength) {
                        double second = (traced - shortLength) / longLength;
                        mark.lineTo(-2 + 13 * second, 7 - 14 * second);
                    }
                    if (check > 0) icon.draw(mark);
                    if (ping > 0) {
                        icon.setComposite(AlphaComposite.SrcOver.derive(messageAlpha * (float) (.45 * ping)));
                        icon.setStroke(new BasicStroke(1.4f, BasicStroke.CAP_ROUND, BasicStroke.JOIN_ROUND));
                        double radius = 27 + 10 * Math.max(0, pingTime);
                        icon.draw(new Ellipse2D.Double(-radius, -radius, radius * 2, radius * 2));
                        for (int i = 0; i < 4; i++) {
                            double angle = Math.PI / 4 + i * Math.PI / 2;
                            double start = radius + 6, end = start + 4 * ping;
                            icon.draw(new java.awt.geom.Line2D.Double(
                                Math.cos(angle) * start, Math.sin(angle) * start,
                                Math.cos(angle) * end, Math.sin(angle) * end));
                        }
                    }
                } finally { icon.dispose(); }
            }
            centered(g, title, w, centerY + 3, 27, Font.BOLD);
            g.setColor(SUBTITLE);
            centered(g, subtitle, w, centerY + 36, 14, Font.PLAIN);
        } finally { g.dispose(); }
    }

    private static double smooth(double value) {
        double t = Math.max(0, Math.min(1, value));
        return t * t * t * (t * (t * 6 - 15) + 10);
    }

    private static void centered(Graphics2D g, String text, int width, int y, int size, int style) {
        g.setFont(StudyTheme.font(style, size));
        g.drawString(text, (width - g.getFontMetrics().stringWidth(text)) / 2, y);
    }
}
