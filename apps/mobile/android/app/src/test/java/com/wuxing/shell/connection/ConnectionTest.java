package com.wuxing.shell.connection;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class ConnectionTest {

    @Test
    public void parse_normalizesHostPortAndBase() {
        Connection c = Connection.parse("192.168.1.5:8723");
        assertNotNull(c);
        assertEquals("http://192.168.1.5:8723", c.baseUrl());
        assertEquals("http://192.168.1.5:8723", c.origin());
    }

    @Test
    public void parse_keepsBasePathAndOriginPort() {
        Connection c = Connection.parse("http://Host:8723/next/");
        assertEquals("http://host:8723/next", c.baseUrl());
        assertEquals("http://host:8723", c.origin());
    }

    @Test
    public void parse_rejectsGarbage() {
        assertNull(Connection.parse(null));
        assertNull(Connection.parse(""));
        assertNull(Connection.parse("ftp://x"));
        assertNull(Connection.parse("http://"));
    }

    @Test
    public void connectUrl_appendsTokenQuery() {
        Connection c = Connection.parse("http://h:8723");
        assertEquals("http://h:8723/?token=abc", c.connectUrl("abc"));
    }

    @Test
    public void isInternal_sameOriginOnly() {
        Connection c = Connection.parse("http://h:8723");
        assertTrue(c.isInternal("http://h:8723/next/"));
        assertTrue(c.isInternal("http://h:8723"));
        assertTrue(c.isInternal("about:blank"));
        assertFalse(c.isInternal("http://h:8723.evil.com/x"));
        assertFalse(c.isInternal("https://h:8723/"));
    }
}
