package com.wuxing.shell.connection;

import java.io.UnsupportedEncodingException;
import java.net.URI;
import java.net.URISyntaxException;
import java.net.URLEncoder;
import java.util.Locale;

/**
 * 连接模型（纯逻辑，JVM 单测覆盖）：URL 规范化 + 令牌换发 URL + 来源白名单。
 *
 * 约定：base = scheme://host[:port][/basePath]（无尾斜杠）；origin = scheme://host[:port]
 * （导航白名单按 origin 严格前缀匹配）。
 */
public final class Connection {

    private final String base;
    private final String origin;

    private Connection(String base, String origin) {
        this.base = base;
        this.origin = origin;
    }

    /** 解析用户输入（允许省略 scheme，默认 http）；非法 → null。 */
    public static Connection parse(String raw) {
        if (raw == null) {
            return null;
        }
        String text = raw.trim();
        if (text.isEmpty()) {
            return null;
        }
        if (!text.contains("://")) {
            text = "http://" + text;
        }
        try {
            URI uri = new URI(text);
            String scheme = uri.getScheme();
            if (scheme == null) {
                return null;
            }
            scheme = scheme.toLowerCase(Locale.ROOT);
            if (!scheme.equals("http") && !scheme.equals("https")) {
                return null;
            }
            String host = uri.getHost();
            if (host == null || host.isEmpty()) {
                return null;
            }
            String origin = scheme + "://" + host.toLowerCase(Locale.ROOT)
                    + (uri.getPort() == -1 ? "" : ":" + uri.getPort());
            String path = uri.getPath() == null ? "" : uri.getPath();
            if (path.endsWith("/")) {
                path = path.substring(0, path.length() - 1);
            }
            return new Connection(origin + path, origin);
        } catch (URISyntaxException e) {
            return null;
        }
    }

    public String baseUrl() {
        return base;
    }

    public String origin() {
        return origin;
    }

    /** 首次访问 URL：`<base>/?token=...`（服务端 302 换 HttpOnly cookie）。
     *  注意：`URLEncoder.encode(String, Charset)` 为 Java 10+ API，Android API 30
     *  运行时不存在（NoSuchMethodError）——必须用 String charset 重载。 */
    public String connectUrl(String token) {
        String value = token == null ? "" : token.trim();
        String encoded;
        try {
            encoded = URLEncoder.encode(value, "UTF-8");
        } catch (UnsupportedEncodingException e) {
            // UTF-8 在所有 Android 版本均可用；此分支仅为满足受检异常签名
            encoded = value;
        }
        return base + "/?token=" + encoded;
    }

    /** 导航白名单：同源与 about:blank 允许留在应用内。 */
    public boolean isInternal(String url) {
        if (url == null) {
            return false;
        }
        String value = url.trim();
        if (value.equals("about:blank")) {
            return true;
        }
        return value.equals(origin) || value.startsWith(origin + "/");
    }
}
