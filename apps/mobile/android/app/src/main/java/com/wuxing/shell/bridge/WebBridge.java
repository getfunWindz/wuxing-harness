package com.wuxing.shell.bridge;

import android.app.Activity;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.webkit.JavascriptInterface;

import com.wuxing.shell.R;

/**
 * WebView 原生桥（最小集）：通知 + 剪贴板。Web 侧以 window.WuxingNative 特性探测。
 * 安全边界：桥注入到本 WebView 的所有页面——由导航同源白名单保证只加载受信页面。
 */
public final class WebBridge {
    public static final String CHANNEL_ID = "wuxing_confirm";

    private final Activity activity;

    public WebBridge(Activity activity) {
        this.activity = activity;
    }

    @JavascriptInterface
    public boolean notify(String title, String body) {
        if (Build.VERSION.SDK_INT >= 33
                && activity.checkSelfPermission("android.permission.POST_NOTIFICATIONS")
                != PackageManager.PERMISSION_GRANTED) {
            return false;
        }
        NotificationManager manager = activity.getSystemService(NotificationManager.class);
        if (manager == null) {
            return false;
        }
        manager.createNotificationChannel(new NotificationChannel(
                CHANNEL_ID, activity.getString(R.string.channel_name),
                NotificationManager.IMPORTANCE_DEFAULT));
        Intent open = new Intent(activity, activity.getClass())
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent pending = PendingIntent.getActivity(activity, 0, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Notification notification = new Notification.Builder(activity, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle(title == null ? "" : title)
                .setContentText(body == null ? "" : body)
                .setContentIntent(pending)
                .setAutoCancel(true)
                .build();
        manager.notify(0, notification);
        return true;
    }

    @JavascriptInterface
    public boolean copy(String text) {
        ClipboardManager manager = (ClipboardManager)
                activity.getSystemService(Context.CLIPBOARD_SERVICE);
        if (manager == null) {
            return false;
        }
        manager.setPrimaryClip(ClipData.newPlainText("WUXING", text == null ? "" : text));
        return true;
    }
}
